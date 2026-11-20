"""parse traced VCD dumps, sample them at clock edges and draw cycle-aligned SVG figures."""
from html import escape

# machine CSR names used when labelling system instructions.
CSR_NAMES = {
    0x300: 'mstatus', 0x301: 'misa', 0x304: 'mie', 0x305: 'mtvec', 0x310: 'mstatush',
    0x320: 'mcountinhibit', 0x340: 'mscratch', 0x341: 'mepc', 0x342: 'mcause', 0x343: 'mtval',
    0x344: 'mip', 0x7b0: 'dcsr', 0x7b1: 'dpc', 0xb00: 'mcycle', 0xb02: 'minstret',
    0xb80: 'mcycleh', 0xb82: 'minstreth', 0xc00: 'cycle', 0xc01: 'time', 0xc02: 'instret',
    0xc80: 'cycleh', 0xc81: 'timeh', 0xc82: 'instreth', 0xf11: 'mvendorid', 0xf12: 'marchid',
    0xf13: 'mimpid', 0xf14: 'mhartid', 0xf15: 'mconfigptr',
}

# light and dark palettes keep figures readable in both repository themes.
STYLE = """
.bg{fill:#ffffff}.frame{fill:none;stroke:#d1d9e0}
.title{fill:#1f2328;font:600 13px sans-serif}.sub{fill:#59636e;font:11px sans-serif}
.lbl{fill:#1f2328;font:11px sans-serif}.num{fill:#59636e;font:9px monospace}
.val{fill:#1f2328;font:10px monospace}.asm{fill:#1f2328;font:10.5px monospace}
.grid{stroke:#e6eaef;stroke-width:1}.edge{stroke:#d1d9e0;stroke-width:1}
.wave{stroke:#0969da;stroke-width:1.5;fill:none}.hi{fill:#0969da;fill-opacity:.12}
.bus{stroke:#57606a;stroke-width:1;fill:#f6f8fa}.idle{stroke:#8c959f;stroke-width:1.2}
.clk{stroke:#59636e;stroke-width:1.2;fill:none}.kill{stroke:#cf222e;stroke-width:1.8}
.mark{stroke:#bf8700;stroke-width:1.2;stroke-dasharray:4 3}.mtext{fill:#9a6700;font:600 10px sans-serif}
.c0{fill:#ddf4ff}.c1{fill:#dafbe1}.c2{fill:#fff8c5}.c3{fill:#ffebe9}
.c4{fill:#fbefff}.c5{fill:#ffeff7}.c6{fill:#d8f3f1}.c7{fill:#fff1e5}
@media (prefers-color-scheme: dark){
.bg{fill:#0d1117}.frame{stroke:#30363d}.title,.lbl,.val,.asm{fill:#e6edf3}.sub,.num{fill:#9198a1}
.grid{stroke:#21262d}.edge{stroke:#30363d}.wave{stroke:#4493f8}.hi{fill:#4493f8;fill-opacity:.18}
.bus{stroke:#8b949e;fill:#161b22}.idle{stroke:#6e7681}.clk{stroke:#9198a1}.kill{stroke:#f85149}
.mark{stroke:#d29922}.mtext{fill:#d29922}
.c0{fill:#0c2d6b}.c1{fill:#033a16}.c2{fill:#3b2300}.c3{fill:#5d0f12}
.c4{fill:#3c1e70}.c5{fill:#5c1f3f}.c6{fill:#04312c}.c7{fill:#4b2306}}
"""


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
    """return width and value changes for the requested full names, plus the dump timescale."""
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
                    info[name] = {'width': int(words[2]), 'changes': []}
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


def text_width(text, size):
    """estimate rendered text width for monospace or proportional labels."""
    return len(text) * size * 0.6


def bus_cells(values, texts, idle, x0, cw):
    """merge equal neighboring cells into labelled bus segments."""
    segments, start = [], 0
    # each change of identity or idle state closes a segment.
    for index in range(1, len(values) + 1):
        # the last cell always closes the final segment.
        if index == len(values) or values[index] != values[start] or idle[index] != idle[start]:
            segments.append((start, index, values[start], texts[start], idle[start]))
            start = index
    return [(x0 + a * cw, x0 + b * cw, value, text, quiet) for a, b, value, text, quiet in segments]


def render(figure):
    """return a self-contained SVG document for one cycle-aligned figure."""
    cw, row_h, label_w, pad = figure.get('cw', 34), 22, 178, 14
    columns = len(figure['cycles'])
    x0 = pad + label_w
    width = x0 + columns * cw + pad
    legend = figure.get('legend', [])
    legend_rows = (len(legend) + 1) // 2
    top = 56 + (28 if figure.get('markers') else 0)
    body_h = len(figure['rows']) * row_h
    height = top + 18 + body_h + (legend_rows * 15 + 22 if legend else 0) + pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(figure["title"])}">',
           f'<title>{escape(figure["title"])}</title>', f'<style>{STYLE}</style>',
           f'<rect class="bg" x="0" y="0" width="{width}" height="{height}" rx="6"/>',
           f'<rect class="frame" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="6"/>',
           f'<text class="title" x="{pad}" y="22">{escape(figure["title"])}</text>',
           f'<text class="sub" x="{pad}" y="40">{escape(figure["subtitle"])}</text>']
    header = top + 12
    # cycle numbers label every column, or every second column when narrow.
    for index, cycle in enumerate(figure['cycles']):
        # narrow columns keep alternate labels legible.
        if cw >= 26 or index % 2 == 0:
            out.append(f'<text class="num" x="{x0 + index * cw + cw / 2:.1f}" y="{header}" text-anchor="middle">{cycle}</text>')
    y = top + 18
    # vertical rules mark each rising clock edge.
    for index in range(columns + 1):
        out.append(f'<line class="grid" x1="{x0 + index * cw}" y1="{y}" x2="{x0 + index * cw}" y2="{y + body_h}"/>')
    # every row is drawn over the shared edge grid.
    for row in figure['rows']:
        mid, high, low = y + row_h / 2, y + 4, y + row_h - 4
        out.append(f'<text class="lbl" x="{x0 - 8}" y="{mid + 4:.1f}" text-anchor="end">{escape(row["label"])}</text>')
        # the clock rises at the left edge of every column.
        if row['kind'] == 'clock':
            points = []
            # each period has a high half followed by a low half.
            for index in range(columns):
                left = x0 + index * cw
                points += [f'{left},{low}', f'{left},{high}', f'{left + cw / 2:.1f},{high}', f'{left + cw / 2:.1f},{low}']
            points.append(f'{x0 + columns * cw},{low}')
            out.append(f'<polyline class="clk" points="{" ".join(points)}"/>')
        # one-bit signals are drawn as levels with shaded high intervals.
        elif row['kind'] == 'bit':
            points, previous = [], None
            # level changes occur only at column boundaries.
            for index, value in enumerate(row['values']):
                left, level = x0 + index * cw, high if value else low
                # a transition adds a vertical step.
                if previous is not None and level != previous:
                    points.append(f'{left},{previous}')
                points.append(f'{left},{level}')
                # high cells receive a light fill.
                if value:
                    out.append(f'<rect class="hi" x="{left}" y="{high}" width="{cw}" height="{low - high}"/>')
                previous = level
            points.append(f'{x0 + columns * cw},{previous}')
            out.append(f'<polyline class="wave" points="{" ".join(points)}"/>')
        # multi-bit and stage rows are drawn as labelled bus segments.
        else:
            idle = row.get('idle', [False] * columns)
            colors = row.get('colors', [None] * columns)
            segments = bus_cells(row['values'], row['texts'], idle, x0, cw)
            # each merged segment is either an idle line or a bounded value.
            for index, (left, right, value, text, quiet) in enumerate(segments):
                # idle intervals carry no value.
                if quiet:
                    out.append(f'<line class="idle" x1="{left}" y1="{mid}" x2="{right}" y2="{mid}"/>')
                    continue
                slant = min(4, (right - left) / 4)
                shape = (f'{left},{mid} {left + slant:.1f},{high} {right - slant:.1f},{high} {right},{mid} '
                         f'{right - slant:.1f},{low} {left + slant:.1f},{low}')
                color = colors[(left - x0) // cw]
                fill = f'bus c{color}' if color is not None else 'bus'
                out.append(f'<polygon class="{fill}" points="{shape}"/>')
                before = segments[index - 1] if index else None
                after = segments[index + 1] if index + 1 < len(segments) else None
                spare = min(before[1] - before[0] if before and before[4] else 0, after[1] - after[0] if after and after[4] else 0)
                width = text_width(text, 10)
                # a label that spills over idle neighbors gets a backing; one that cannot fit is omitted.
                if text and width > right - left - 4 and width <= right - left - 4 + 2 * spare:
                    out.append(f'<rect class="bg" x="{(left + right - width) / 2 - 2:.1f}" y="{mid - 6:.1f}" width="{width + 4:.1f}" height="12" rx="2"/>')
                # labels are centred on their segment.
                if text and width <= right - left - 4 + 2 * spare:
                    out.append(f'<text class="val" x="{(left + right) / 2:.1f}" y="{mid + 3.5:.1f}" text-anchor="middle">{escape(text)}</text>')
            # killed tokens are crossed out in the cycle of their kill.
            for index, killed in enumerate(row.get('kills', [])):
                # only killed cells receive a cross.
                if killed:
                    left = x0 + index * cw
                    out.append(f'<line class="kill" x1="{left + 5}" y1="{high + 1}" x2="{left + cw - 5}" y2="{low - 1}"/>')
                    out.append(f'<line class="kill" x1="{left + cw - 5}" y1="{high + 1}" x2="{left + 5}" y2="{low - 1}"/>')
        y += row_h
    ends = [float('-inf'), float('-inf')]
    # markers sit on the clock edge where the named event takes effect; close labels use a second line.
    for marker in figure.get('markers', []):
        left = x0 + marker['column'] * cw
        level = 0 if left + 3 > ends[0] + 6 else 1
        ends[level] = left + 3 + text_width(marker['label'], 10)
        out.append(f'<line class="mark" x1="{left}" y1="{top - 14 + 12 * level}" x2="{left}" y2="{top + 18 + body_h}"/>')
        out.append(f'<text class="mtext" x="{left + 3}" y="{top - 10 + 12 * level}">{escape(marker["label"])}</text>')
    # the program listing names each instruction shown in the stage rows.
    if legend:
        base = top + 18 + body_h + 24
        column_w = (width - 2 * pad) / 2
        # entries fill the left column before the right column.
        for index, (color, address, text) in enumerate(legend):
            column, line = divmod(index, legend_rows)
            left, top_y = pad + column * column_w, base + line * 15
            swatch = f'bus c{color}' if color is not None else 'bus'
            out.append(f'<rect class="{swatch}" x="{left:.1f}" y="{top_y - 9}" width="10" height="10" rx="2"/>')
            out.append(f'<text class="asm" x="{left + 16:.1f}" y="{top_y}">{escape(address)}  {escape(text)}</text>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'
