"""parse traced VCD dumps, sample them at clock edges and export or prepare cycle windows for gtkwave."""
import contextlib
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

# machine CSR names used when labelling system instructions.
CSR_NAMES = {
    0x300: 'mstatus', 0x301: 'misa', 0x304: 'mie', 0x305: 'mtvec', 0x310: 'mstatush',
    0x320: 'mcountinhibit', 0x340: 'mscratch', 0x341: 'mepc', 0x342: 'mcause', 0x343: 'mtval',
    0x344: 'mip', 0x7b0: 'dcsr', 0x7b1: 'dpc', 0xb00: 'mcycle', 0xb02: 'minstret',
    0xb80: 'mcycleh', 0xb82: 'minstreth', 0xc00: 'cycle', 0xc01: 'time', 0xc02: 'instret',
    0xc80: 'cycleh', 0xc81: 'timeh', 0xc82: 'instreth', 0xf11: 'mvendorid', 0xf12: 'marchid',
    0xf13: 'mimpid', 0xf14: 'mhartid', 0xf15: 'mconfigptr',
}

def sign(value, bits):
    """interpret the low bits of value as a two's-complement number."""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def csr_name(address):
    """name a machine CSR address or print it in hexadecimal."""
    return CSR_NAMES.get(address, f'0x{address:03x}')


def disassemble32(raw, pc):
    """return assembly text for one supported 32-bit instruction encoding."""
    opcode, rd, funct3 = raw & 0x7f, (raw >> 7) & 31, (raw >> 12) & 7
    rs1, rs2, funct7 = (raw >> 15) & 31, (raw >> 20) & 31, raw >> 25
    imm_i = sign(raw >> 20, 12)
    imm_s = sign(((raw >> 25) << 5) | ((raw >> 7) & 31), 12)
    imm_b = sign((((raw >> 31) & 1) << 12) | (((raw >> 7) & 1) << 11) | (((raw >> 25) & 0x3f) << 5) |
                 (((raw >> 8) & 0xf) << 1), 13)
    imm_j = sign((((raw >> 31) & 1) << 20) | (((raw >> 12) & 0xff) << 12) | (((raw >> 20) & 1) << 11) |
                 (((raw >> 21) & 0x3ff) << 1), 21)
    loads = {0: 'lb', 1: 'lh', 2: 'lw', 4: 'lbu', 5: 'lhu'}
    stores = {0: 'sb', 1: 'sh', 2: 'sw'}
    branches = {0: 'beq', 1: 'bne', 4: 'blt', 5: 'bge', 6: 'bltu', 7: 'bgeu'}
    immediates = {0: 'addi', 2: 'slti', 3: 'sltiu', 4: 'xori', 6: 'ori', 7: 'andi'}
    registers = {(0, 0): 'add', (0x20, 0): 'sub', (0, 1): 'sll', (0, 2): 'slt', (0, 3): 'sltu',
                 (0, 4): 'xor', (0, 5): 'srl', (0x20, 5): 'sra', (0, 6): 'or', (0, 7): 'and',
                 (1, 0): 'mul', (1, 1): 'mulh', (1, 2): 'mulhsu', (1, 3): 'mulhu',
                 (1, 4): 'div', (1, 5): 'divu', (1, 6): 'rem', (1, 7): 'remu'}
    system = {0x00000073: 'ecall', 0x00100073: 'ebreak', 0x30200073: 'mret', 0x10500073: 'wfi'}
    csr_ops = {1: 'csrrw', 2: 'csrrs', 3: 'csrrc', 5: 'csrrwi', 6: 'csrrsi', 7: 'csrrci'}
    # upper immediates and jumps carry their own operand layouts.
    if opcode == 0x37:
        return f'lui x{rd}, 0x{raw >> 12:x}'
    # pc-relative upper immediates add to the instruction address.
    if opcode == 0x17:
        return f'auipc x{rd}, 0x{raw >> 12:x}'
    # jump targets are shown as absolute addresses.
    if opcode == 0x6f:
        return f'jal x{rd}, 0x{(pc + imm_j) & 0xffffffff:x}'
    # register-indirect jumps keep their base and offset.
    if opcode == 0x67 and funct3 == 0:
        return f'jalr x{rd}, {imm_i}(x{rs1})'
    # conditional branches show their taken target.
    if opcode == 0x63 and funct3 in branches:
        return f'{branches[funct3]} x{rs1}, x{rs2}, 0x{(pc + imm_b) & 0xffffffff:x}'
    # loads name their destination and effective-address operands.
    if opcode == 0x03 and funct3 in loads:
        return f'{loads[funct3]} x{rd}, {imm_i}(x{rs1})'
    # stores name their data and effective-address operands.
    if opcode == 0x23 and funct3 in stores:
        return f'{stores[funct3]} x{rs2}, {imm_s}(x{rs1})'
    # register-immediate arithmetic includes the canonical no-op.
    if opcode == 0x13:
        # the canonical no-op is named explicitly.
        if raw == 0x00000013:
            return 'nop'
        # shifts encode their amount in the immediate field.
        if funct3 in (1, 5):
            name = {(0, 1): 'slli', (0, 5): 'srli', (0x20, 5): 'srai'}.get((funct7, funct3))
            return f'{name} x{rd}, x{rs1}, {rs2}' if name else f'.word 0x{raw:08x}'
        return f'{immediates[funct3]} x{rd}, x{rs1}, {imm_i}'
    # register-register arithmetic includes the M extension.
    if opcode == 0x33 and (funct7, funct3) in registers:
        return f'{registers[(funct7, funct3)]} x{rd}, x{rs1}, x{rs2}'
    # memory ordering distinguishes data fences from instruction synchronization.
    if opcode == 0x0f:
        return 'fence.i' if funct3 == 1 else ('fence' if funct3 == 0 else f'.word 0x{raw:08x}')
    # exact system encodings precede CSR decoding.
    if raw in system:
        return system[raw]
    # CSR forms use a register or a five-bit immediate source.
    if opcode == 0x73 and funct3 in csr_ops:
        source = str(rs1) if funct3 >= 5 else f'x{rs1}'
        return f'{csr_ops[funct3]} x{rd}, {csr_name(raw >> 20)}, {source}'
    return f'.word 0x{raw:08x}'


def disassemble16(raw, pc):
    """return assembly text for one RV32C halfword encoding."""
    quadrant, funct3 = raw & 3, (raw >> 13) & 7
    rd, rs2 = (raw >> 7) & 31, (raw >> 2) & 31
    rdp, rs2p = ((raw >> 7) & 7) + 8, ((raw >> 2) & 7) + 8
    imm6 = sign((((raw >> 12) & 1) << 5) | ((raw >> 2) & 31), 6)
    offset_j = sign((((raw >> 12) & 1) << 11) | (((raw >> 8) & 1) << 10) | (((raw >> 9) & 3) << 8) |
                    (((raw >> 6) & 1) << 7) | (((raw >> 7) & 1) << 6) | (((raw >> 2) & 1) << 5) |
                    (((raw >> 11) & 1) << 4) | (((raw >> 3) & 7) << 1), 12)
    offset_b = sign((((raw >> 12) & 1) << 8) | (((raw >> 5) & 3) << 6) | (((raw >> 2) & 1) << 5) |
                    (((raw >> 10) & 3) << 3) | (((raw >> 3) & 3) << 1), 9)
    word = (((raw >> 10) & 7) << 3) | (((raw >> 6) & 1) << 2) | (((raw >> 5) & 1) << 6)
    # quadrant zero holds stack-relative and compressed-register memory forms.
    if quadrant == 0:
        # an all-zero halfword is defined as illegal.
        if raw == 0:
            return 'c.unimp'
        # the scaled stack offset forms a register address.
        if funct3 == 0:
            scaled = (((raw >> 7) & 0xf) << 6) | (((raw >> 11) & 3) << 4) | (((raw >> 5) & 1) << 3) | (((raw >> 6) & 1) << 2)
            return f'c.addi4spn x{rs2p}, sp, {scaled}'
        # word loads and stores use compressed register numbers.
        if funct3 in (2, 6):
            return f'c.lw x{rs2p}, {word}(x{rdp})' if funct3 == 2 else f'c.sw x{rs2p}, {word}(x{rdp})'
    # quadrant one holds immediates, jumps and compressed-register arithmetic.
    elif quadrant == 1:
        # immediate addition reserves rd zero for the compressed no-op.
        if funct3 == 0:
            return 'c.nop' if rd == 0 else f'c.addi x{rd}, {imm6}'
        # RV32 uses this encoding for the linking jump.
        if funct3 in (1, 5):
            return f'{"c.jal" if funct3 == 1 else "c.j"} 0x{(pc + offset_j) & 0xffffffff:x}'
        # load-immediate writes a sign-extended six-bit value.
        if funct3 == 2:
            return f'c.li x{rd}, {imm6}'
        # register two adjusts the stack pointer; other registers load an upper immediate.
        if funct3 == 3:
            # the stack adjustment uses a separately scaled immediate.
            if rd == 2:
                scaled = sign((((raw >> 12) & 1) << 9) | (((raw >> 6) & 1) << 4) | (((raw >> 5) & 1) << 6) |
                              (((raw >> 3) & 3) << 7) | (((raw >> 2) & 1) << 5), 10)
                return f'c.addi16sp sp, {scaled}'
            return f'c.lui x{rd}, 0x{imm6 & 0xfffff:x}'
        # compressed-register arithmetic selects shifts, masks or register operations.
        if funct3 == 4:
            group = (raw >> 10) & 3
            amount = (((raw >> 12) & 1) << 5) | ((raw >> 2) & 31)
            # shifts and masks take immediates.
            if group < 3:
                return f'{("c.srli", "c.srai", "c.andi")[group]} x{rdp}, {amount if group < 2 else imm6}'
            return f'{("c.sub", "c.xor", "c.or", "c.and")[(raw >> 5) & 3]} x{rdp}, x{rs2p}'
        # zero-comparison branches show their target.
        if funct3 in (6, 7):
            return f'{"c.beqz" if funct3 == 6 else "c.bnez"} x{rdp}, 0x{(pc + offset_b) & 0xffffffff:x}'
    # quadrant two holds stack-relative memory, moves and register jumps.
    elif quadrant == 2:
        # left shifts use a six-bit amount whose high bit must be zero on RV32.
        if funct3 == 0:
            return f'c.slli x{rd}, {(((raw >> 12) & 1) << 5) | rs2}'
        # stack-relative word loads scale their offset.
        if funct3 == 2:
            return f'c.lwsp x{rd}, {(((raw >> 12) & 1) << 5) | (((raw >> 4) & 7) << 2) | (((raw >> 2) & 3) << 6)}(sp)'
        # bit twelve selects moves and jumps or additions, linking jumps and breakpoints.
        if funct3 == 4:
            # jumps through a register have no second source.
            if not (raw >> 12) & 1:
                return f'c.jr x{rd}' if rs2 == 0 else f'c.mv x{rd}, x{rs2}'
            # the breakpoint has neither register.
            if rd == 0 and rs2 == 0:
                return 'c.ebreak'
            return f'c.jalr x{rd}' if rs2 == 0 else f'c.add x{rd}, x{rs2}'
        # stack-relative word stores scale their offset.
        if funct3 == 6:
            return f'c.swsp x{rs2}, {(((raw >> 9) & 0xf) << 2) | (((raw >> 7) & 3) << 6)}(sp)'
    return f'.half 0x{raw & 0xffff:04x}'


def disassemble(raw, pc, length):
    """choose the compressed or full decoder from the recorded instruction length."""
    return disassemble16(raw & 0xffff, pc) if length == 2 else disassemble32(raw, pc)


def parse_vcd(path, wanted):
    """return width, declared range and value changes for the requested full names, plus the dump timescale."""
    codes, info, timescale, scope = {}, {}, '', []
    # one pass reads declarations, then only the retained value changes.
    with open(path, 'r', encoding='ascii', errors='replace') as stream:
        # declarations map identifier codes to hierarchical names.
        for line in stream:
            words = line.split()
            # empty lines carry no declaration.
            if not words:
                continue
            # scopes nest the following variable names.
            if words[0] == '$scope':
                scope.append(words[2])
            # closing a scope restores its parent.
            elif words[0] == '$upscope':
                scope.pop()
            # each variable may alias another identifier code.
            elif words[0] == '$var':
                name = '.'.join(scope + [words[4]])
                # only requested names are retained.
                if name in wanted:
                    codes.setdefault(words[3], []).append(name)
                    info[name] = {'width': int(words[2]), 'range': '' if words[5] == '$end' else words[5], 'changes': []}
            # the timescale applies to every recorded time.
            elif words[0] == '$timescale':
                timescale = ' '.join(word for word in words[1:] if word != '$end')
            # value changes follow the definition section.
            elif words[0] == '$enddefinitions':
                break
        time = 0
        # value-change records update only retained identifier codes.
        for line in stream:
            head = line[:1]
            # timestamps order every later change.
            if head == '#':
                time = int(line[1:])
            # scalar changes carry the value before the identifier code.
            elif head in '01xzXZ' and head:
                names = codes.get(line[1:].strip())
                # unretained identifiers are skipped.
                if names:
                    value = 1 if head == '1' else 0
                    # aliases share one value stream.
                    for name in names:
                        info[name]['changes'].append((time, value))
            # vector changes give binary digits and the identifier code.
            elif head in 'bB':
                digits, _, code = line[1:].partition(' ')
                names = codes.get(code.strip())
                # unretained identifiers are skipped.
                if names:
                    value = int(digits.translate(str.maketrans('xzXZ', '0000')), 2)
                    # aliases share one value stream.
                    for name in names:
                        info[name]['changes'].append((time, value))
    missing = sorted(set(wanted) - set(info))
    # a misspelled or absent signal must not silently disappear from a figure.
    if missing:
        raise KeyError('signals absent from dump: ' + ', '.join(missing))
    return info, timescale


def rising_edges(changes):
    """return the times at which a one-bit signal rises."""
    edges, previous = [], 0
    # a rise is a zero-to-one transition.
    for time, value in changes:
        # repeated values are not transitions.
        if value and not previous:
            edges.append(time)
        previous = value
    return edges


def sample(changes, times):
    """return each value held strictly before the corresponding sorted sample time."""
    values, index, current = [], 0, 0
    # walk both sorted sequences once.
    for time in times:
        # adopt every change that precedes this sample time.
        while index < len(changes) and changes[index][0] < time:
            current = changes[index][1]
            index += 1
        values.append(current)
    return values


# gtkwave save-file flags for the display formats a figure requests.
FLAGS = {'bit': '@28', 'bin': '@28', 'hex': '@22', 'dec': '@24'}
# tcl metacharacters are rejected in marker labels, which are passed literally.
TCL_UNSAFE = set('"\\[]{}$;')
# an interactive view opens at this window width; the margin is what gtkwave draws beside the two panes.
VIEW_WIDTH, VIEW_MARGIN = 1500, 70
# at zoom z, gtkwave draws the whole part of 2**-z time units across one frame of this many pixels.
ZOOM_FRAME = 200
# gtkwave keeps twenty-six named markers, lettered from A.
MARKER_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def trace_lines(traces):
    """return the save-file lines that list aliased traces in order with their display formats."""
    lines, flag = [], None
    # a format line applies to every following trace until the next format line.
    for fmt, alias, name in traces:
        # emit a format line only when the format changes.
        if FLAGS[fmt] != flag:
            flag = FLAGS[fmt]
            lines.append(flag)
        lines.append(f'+{{{alias}}} {name}')
    return lines


def save_file(path, dump, traces, width, signals_width):
    """write a gtkwave save file that loads one dump and lists aliased traces in order."""
    lines = [f'[dumpfile] "{dump}"', '[timestart] 0', f'[size] {width} {120 + 21 * len(traces)}', '[pos] 0 0',
             '[sst_expanded] 0', '[sst_width] 1', f'[signals_width] {signals_width}']
    Path(path).write_text('\n'.join(lines + trace_lines(traces)) + '\n')


def view_file(path, dump, traces, start, end, markers):
    """write a gtkwave save file that itself carries the time window and named markers of one figure."""
    signals_width = max(190, 9 * max(len(alias) for _, alias, _ in traces) + 50)
    pixels = max(200, VIEW_WIDTH - signals_width - VIEW_MARGIN)
    # the window must fit the wave pane, so a longer window needs a more negative zoom.
    # gtkwave truncates the time units per frame, so the count is rounded up to keep the last cycles in view.
    zoom = -math.log2(max(1, math.ceil((end - start) * ZOOM_FRAME / pixels)))
    times = ['-1'] * len(MARKER_LETTERS)
    names = []
    # each named marker fills the slot of its letter; unused slots stay at -1.
    for letter, time, label in markers:
        # a marker needs one known letter, and its label is the rest of a save-file line.
        if len(letter) != 1 or letter not in MARKER_LETTERS or '\n' in label or '\r' in label:
            raise ValueError(f'unsafe marker: {letter!r} {label!r}')
        times[MARKER_LETTERS.index(letter)] = str(time)
        names.append(f'[markername] {letter}{label}')
    # the second field of the zoom line is the primary marker, which a view leaves unset.
    lines = [f'[dumpfile] "{dump}"', f'[timestart] {max(0, start)}',
             f'[size] {VIEW_WIDTH} {150 + 24 * len(traces)}', '[pos] -1 -1',
             f'*{zoom:.6f} -1 ' + ' '.join(times), *names,
             '[sst_expanded] 0', '[sst_width] 1', f'[signals_width] {signals_width}']
    Path(path).write_text('\n'.join(lines + trace_lines(traces)) + '\n')


def grab_script(path, start, end, markers, image):
    """write a timer-driven gtkwave script that zooms, names markers, grabs the window and quits."""
    lines = ['if {![info exists ::step]} { set ::step 0 }', 'incr ::step', 'if {$::step == 1} {',
             f'  gtkwave::setZoomRangeTimes {start} {end}']
    # each named marker labels the clock edge of one event.
    for letter, edge, label in markers:
        # a label containing tcl syntax could change the script, so it is refused.
        if TCL_UNSAFE & set(label):
            raise ValueError(f'unsafe marker label: {label}')
        lines.append(f'  gtkwave::setNamedMarker {letter} {edge} "{label}"')
    lines += ['} elseif {$::step == 4} {', f'  gtkwave::/File/Grab_To_File {image}',
              '} elseif {$::step >= 5} {', '  gtkwave::/File/Quit', '}']
    Path(path).write_text('\n'.join(lines) + '\n')


@contextlib.contextmanager
def x_display(width, height):
    """start a private X server whose root window gtkwave can read back for screen grabs."""
    number = next(n for n in range(90, 200)
                  if not os.path.exists(f'/tmp/.X11-unix/X{n}') and not os.path.exists(f'/tmp/.X{n}-lock'))
    # a virtual framebuffer needs no desktop session.
    if shutil.which('Xvfb'):
        command = ['Xvfb', f':{number}', '-screen', '0', f'{width}x{height}x24', '-nolisten', 'tcp']
    # inside a wayland session, a rootful xwayland window keeps its own readable framebuffer.
    elif shutil.which('Xwayland') and os.environ.get('WAYLAND_DISPLAY'):
        command = ['Xwayland', f':{number}', '-geometry', f'{width}x{height}', '-shm', '-nolisten', 'tcp']
    # without either server there is no screen to grab.
    else:
        raise RuntimeError('gtkwave export needs Xvfb, or Xwayland inside a wayland session')
    server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # the private server is stopped even when an export fails.
    try:
        deadline = time.monotonic() + 10
        # clients connect only after the server has created its socket.
        while not os.path.exists(f'/tmp/.X11-unix/X{number}'):
            # a server that exits or never creates its socket cannot be used.
            if time.monotonic() > deadline or server.poll() is not None:
                raise RuntimeError('X server did not start: ' + ' '.join(command))
            time.sleep(0.1)
        yield f':{number}', command[0]
    # every figure has been exported or the run has failed.
    finally:
        server.terminate()
        server.wait(timeout=10)


def export(gtkwave, directory, dump, save, script, image, display, rcfile, log):
    """run gtkwave on one dump inside the private display and require its grabbed image."""
    # the x11 backend keeps gtkwave inside the private display, and server-side decorations avoid an empty
    # shadow margin around the grabbed window.
    environment = dict(os.environ, DISPLAY=display, GDK_BACKEND='x11', GTK_CSD='0')
    environment.pop('WAYLAND_DISPLAY', None)
    command = [gtkwave, '-r', rcfile, dump, save, f'--repscript={script}', '--repperiod=400']
    result = subprocess.run([str(part) for part in command], cwd=directory, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=300)
    Path(log).write_text('$ ' + ' '.join(str(part) for part in command) + '\n' + result.stdout)
    target = Path(directory) / image
    # gtkwave must exit normally and leave the grabbed image behind.
    if result.returncode or not target.is_file():
        raise RuntimeError(f'gtkwave export failed: {log}')
    return target, command
