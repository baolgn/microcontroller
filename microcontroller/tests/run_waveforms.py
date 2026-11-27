#!/usr/bin/env python3
"""run traced simulation fixtures and export their cycle windows from gtkwave as figures, or prepare them as views."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location('waveform_render', HERE / 'waveform_render.py')
wave = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wave)
RTL = 'microcontroller/rtl/'
TESTS = 'microcontroller/tests/'
# operation names for trusted packets that carry no raw instruction.
OPS = ['result', 'load', 'store', 'csr', 'mret', 'ecall', 'ebreak', 'redirect', 'control', 'memory',
       'base', 'fence', 'machine', 'wfi', 'fence.i']
RAW_OPS = {8, 9, 10, 12}


def rtl(*names):
    """return repository paths for the named RTL modules."""
    return [RTL + name + '.sv' for name in names]


CORE = rtl('cpu5_control_pkg', 'cpu5_decoder', 'cpu5_decompress', 'cpu5_immediate', 'cpu5_branch', 'cpu5_lsu',
           'cpu5_shifter', 'cpu5_alu', 'cpu5_forward', 'cpu5_csr', 'cpu5_control')
FRONT = rtl('cpu5_control_pkg', 'cpu5_immediate', 'cpu5_decoder', 'cpu5_branch', 'cpu5_lsu', 'cpu5_shifter',
            'cpu5_alu', 'cpu5_forward', 'cpu5_decompress', 'cpu5_fetch_guard', 'cpu5_fetch_buffer', 'cpu5_fetch',
            'cpu5_frontend', 'cpu5_csr', 'cpu5_muldiv', 'cpu5_control')

# each bench repeats its owning runner's sources, parameters and pass marker; tracing is the only addition.
BENCHES = {
    'base-forwarded': {'top': 'cpu5_base_tb', 'sources': CORE + [TESTS + 'cpu5_base_tb.sv'],
                       'params': {'DIAGNOSTIC': 0, 'FORWARDING': 1}, 'seeded': True, 'pass': 'PASS base ',
                       'runner': 'run_base.py'},
    'base-diagnostic': {'top': 'cpu5_base_tb', 'sources': CORE + [TESTS + 'cpu5_base_tb.sv'],
                        'params': {'DIAGNOSTIC': 1, 'FORWARDING': 0}, 'seeded': True, 'pass': 'PASS base ',
                        'runner': 'run_base.py'},
    'memory-base': {'top': 'cpu5_memory_tb', 'sources': CORE + [TESTS + 'cpu5_memory_tb.sv'],
                    'params': {'PROFILE': 0, 'MAX_WAIT': 128, 'SCENARIO': 0}, 'seeded': True,
                    'pass': 'PASS memory ', 'runner': 'run_memory.py'},
    'csr-control': {'top': 'cpu5_csr_control_tb', 'sources': CORE + [TESTS + 'cpu5_csr_control_tb.sv'],
                    'params': {'C_ENABLED': 0}, 'seeded': True, 'pass': 'PASS csr-control ',
                    'runner': 'run_csr_control.py'},
    'muldiv-forwarded': {'top': 'cpu5_muldiv_control_tb',
                         'sources': rtl('cpu5_control_pkg', 'cpu5_decoder', 'cpu5_decompress', 'cpu5_immediate',
                                        'cpu5_branch', 'cpu5_lsu', 'cpu5_shifter', 'cpu5_alu', 'cpu5_forward',
                                        'cpu5_muldiv', 'cpu5_csr', 'cpu5_irq_platform', 'cpu5_control') +
                         [TESTS + 'cpu5_muldiv_control_tb.sv'],
                         'params': {'M_ENABLED': 1, 'DIAGNOSTIC': 0, 'FORWARDING': 1, 'IRQ_ENABLED': 1},
                         'seeded': True, 'pass': 'PASS muldiv-control ', 'runner': 'run_muldiv_control.py'},
    'irq-control': {'top': 'cpu5_irq_control_tb',
                    'sources': rtl('cpu5_control_pkg', 'cpu5_decoder', 'cpu5_decompress', 'cpu5_immediate',
                                   'cpu5_branch', 'cpu5_lsu', 'cpu5_shifter', 'cpu5_alu', 'cpu5_forward', 'cpu5_csr',
                                   'cpu5_irq_platform', 'cpu5_control') + [TESTS + 'cpu5_irq_control_tb.sv'],
                    'params': {'C_ENABLED': 0}, 'seeded': True, 'pass': 'PASS irq-control ',
                    'runner': 'run_irq_control.py'},
    'compressed': {'top': 'cpu5_compressed_execution_tb', 'sources': FRONT + [TESTS + 'cpu5_compressed_execution_tb.sv'],
                   'params': {'C_ENABLED': 1, 'M_ENABLED': 1, 'DIAGNOSTIC': 0, 'FORWARDING': 1}, 'seeded': True,
                   'pass': 'C_EXEC_PASS ', 'runner': 'run_compressed_execution.py'},
    'fence': {'top': 'cpu5_fence_execution_tb', 'sources': FRONT + [TESTS + 'cpu5_fence_execution_tb.sv'],
              'params': {'C_ENABLED': 1, 'ZIFENCEI_ENABLED': 1, 'DIAGNOSTIC': 0, 'FORWARDING': 1}, 'seeded': True,
              'pass': 'FENCE_EXEC_PASS ', 'runner': 'run_fence_execution.py'},
    'debug-core': {'top': 'cpu5_debug_core_tb',
                   'sources': rtl('cpu5_control_pkg', 'cpu5_decoder', 'cpu5_decompress', 'cpu5_immediate',
                                  'cpu5_branch', 'cpu5_lsu', 'cpu5_shifter', 'cpu5_alu', 'cpu5_forward', 'cpu5_csr',
                                  'cpu5_muldiv', 'cpu5_control') + [TESTS + 'cpu5_debug_core_tb.sv'],
                   'params': {'C_ENABLED': 0, 'DIAGNOSTIC': 0}, 'seeded': True, 'pass': 'PASS debug-core ',
                   'runner': 'run_debug_core.py'},
    'local-fabric': {'top': 'cpu5_local_fabric_tb',
                     'sources': rtl('cpu5_irq_platform', 'cpu5_local_fabric') + [TESTS + 'cpu5_local_fabric_tb.sv'],
                     'params': {}, 'seeded': False, 'pass': 'LOCAL_FABRIC_PASS', 'runner': 'run_local_fabric.py'},
    'irq-platform': {'top': 'cpu5_irq_platform_tb',
                     'sources': rtl('cpu5_irq_platform') + [TESTS + 'cpu5_irq_platform_tb.sv'],
                     'params': {}, 'seeded': True, 'pass': 'PASS irq-platform ', 'runner': 'run_irq_platform.py'},
}

def stage_rows(prefix):
    """expand the five pipeline stages of a control instance into stage rows."""
    return [('stage', name, prefix, index) for index, name in enumerate(['F', 'D', 'X', 'M', 'W'])]


# every bench samples its own fixture clock.
CLOCKS = {'base-forwarded': 'cpu5_base_tb.clk_i', 'base-diagnostic': 'cpu5_base_tb.clk_i',
          'memory-base': 'cpu5_memory_tb.clk_i', 'csr-control': 'cpu5_csr_control_tb.clk_i',
          'muldiv-forwarded': 'cpu5_muldiv_control_tb.clk_i', 'irq-control': 'cpu5_irq_control_tb.clk_i',
          'compressed': 'cpu5_compressed_execution_tb.clk_i', 'fence': 'cpu5_fence_execution_tb.clk_i',
          'debug-core': 'cpu5_debug_core_tb.clk_i',
          'local-fabric': 'cpu5_local_fabric_tb.clk', 'irq-platform': 'cpu5_irq_platform_tb.clk_i'}
HEX, DEC, BIN2 = 'hex', 'dec', 'bin'
BASE, MEM, CSR = 'cpu5_base_tb.dut', 'cpu5_memory_tb.dut', 'cpu5_csr_control_tb.dut'
IRQ, MD, FEN = 'cpu5_irq_control_tb.dut', 'cpu5_muldiv_control_tb.dut', 'cpu5_fence_execution_tb.dut'
CMP, DBG = 'cpu5_compressed_execution_tb.dut', 'cpu5_debug_core_tb.dut'
FAB, NOTE = 'cpu5_local_fabric_tb.dut', 'cpu5_irq_platform_tb.platforms[1].dut'


def held(path):
    """name the valid bit that qualifies a bus value; the value is hidden while it is low."""
    return path


def raw_at(prefix, stage, s, c):
    """return the original instruction bits held by one stage, or zero when empty."""
    return s(f'{prefix}.stage_token_o[{stage}].p.raw', c) if (s(f'{prefix}.stage_valid_o', c) >> stage) & 1 else 0


def first(s, c, condition, limit):
    """return the first cycle after c within limit cycles where condition holds, or none."""
    return next((k for k in range(c + 1, c + limit + 1) if condition(s, k)), None)


# each figure isolates one mechanism; captions in the guides describe exactly these windows.
FIGURES = [
    {'id': 'pipeline-overlap', 'guide': 'microcontroller/README.md', 'bench': 'base-forwarded', 'seed': 1,
     'title': 'overlapped five-stage execution with forwarding',
     'rows': [*stage_rows(BASE), ('retire', 'trace_o', BASE)],
     'trigger': lambda s, c: s(f'{BASE}.stage_valid_o', c) == 0x1f, 'before': 4, 'after': 11,
     'markers': [('all five stages occupied', lambda s, c: s(f'{BASE}.stage_valid_o', c) == 0x1f)],
     'requires': [('every stage stays occupied', lambda s, k: all(s(f'{BASE}.stage_valid_o', c) == 0x1f for c in range(k, k + 12))),
                  ('no operand stall occurs', lambda s, k: not any(s(f'{BASE}.d_hazard', c) for c in range(k - 4, k + 12))),
                  ('one trace record follows every edge', lambda s, k: all(s(f'{BASE}.trace_o.valid', c) for c in range(k + 1, k + 12)))],
     'extra': [f'{BASE}.d_hazard']},
    {'id': 'diagnostic-mode', 'guide': 'microcontroller/rtl/README.md', 'bench': 'base-diagnostic', 'seed': 1,
     'title': 'diagnostic profile: one instruction in flight',
     'rows': [*stage_rows(BASE), ('bit', 'in_ready_o', f'{BASE}.in_ready_o'), ('retire', 'trace_o', BASE)],
     'trigger': lambda s, c: s(f'{BASE}.stage_valid_o', c) != 0, 'before': 1, 'after': 24,
     'requires': [('at most one stage is occupied', lambda s, k: all(bin(s(f'{BASE}.stage_valid_o', c)).count('1') <= 1 for c in range(k - 1, k + 25)))]},
    {'id': 'load-use-stall', 'guide': 'microcontroller/rtl/README.md', 'bench': 'base-forwarded', 'seed': 1,
     'title': 'load-use hazard: the consumer waits for the completed load',
     'rows': [*stage_rows(BASE), ('bit', 'd_hazard', f'{BASE}.d_hazard'), ('bit', 'd_req_valid_o', f'{BASE}.d_req_valid_o'),
              ('bit', 'd_req_ready_i', f'{BASE}.d_req_ready_i'), ('bus', 'd_req_addr_o', f'{BASE}.d_req_addr_o', HEX, held(f'{BASE}.d_req_valid_o')),
              ('bit', 'd_rsp_valid_i', f'{BASE}.d_rsp_valid_i'), ('retire', 'trace_o', BASE)],
     'trigger': lambda s, c: s(f'{BASE}.d_hazard', c) and raw_at(BASE, 2, s, c) & 0x7f == 0x03, 'before': 3, 'after': 13,
     'markers': [('offer', lambda s, c: s(f'{BASE}.d_req_valid_o', c)),
                 ('accept', lambda s, c: s(f'{BASE}.d_req_valid_o', c) and s(f'{BASE}.d_req_ready_i', c)),
                 ('response', lambda s, c: s(f'{BASE}.d_rsp_valid_i', c))],
     'requires': [('the consumer is held until the response', lambda s, k: all(s(f'{BASE}.d_hazard', c) for c in range(k, first(s, k, lambda s, c: s(f'{BASE}.d_rsp_valid_i', c), 20) + 1))),
                  ('the hazard clears after the response', lambda s, k: not s(f'{BASE}.d_hazard', first(s, k, lambda s, c: s(f'{BASE}.d_rsp_valid_i', c), 20) + 1))]},
    {'id': 'branch-redirect', 'guide': 'microcontroller/rtl/README.md', 'bench': 'base-forwarded', 'seed': 1,
     'title': 'taken branch: target calculated in X, redirect committed at W',
     'rows': [*stage_rows(BASE), ('retire', 'trace_o', BASE), ('bit', 'redirect_valid_o', f'{BASE}.redirect_valid_o'),
              ('bus', 'redirect_pc_o', f'{BASE}.redirect_pc_o', HEX, held(f'{BASE}.redirect_valid_o'))],
     'trigger': lambda s, c: s(f'{BASE}.redirect_valid_o', c) and s(f'{BASE}.redirect_pc_o', c) != 0x1f00, 'before': 8, 'after': 4,
     'markers': [('branch in X', lambda s, c: raw_at(BASE, 2, s, c) & 0x7f == 0x63),
                 ('branch in W', lambda s, c: raw_at(BASE, 4, s, c) & 0x7f == 0x63),
                 ('redirect', lambda s, c: s(f'{BASE}.redirect_valid_o', c))],
     'kills': True,
     'requires': [('younger tokens are killed with the redirect', lambda s, k: s(f'{BASE}.kill_valid_o', k) != 0),
                  ('the branch reaches W immediately before the redirect', lambda s, k: raw_at(BASE, 4, s, k - 1) & 0x7f == 0x63)],
     'extra': [f'{BASE}.kill_valid_o']},
    {'id': 'data-request', 'guide': 'microcontroller/rtl/README.md', 'bench': 'memory-base', 'seed': 1,
     'title': 'first-valid data request: stable offer, single acceptance, owned response',
     'rows': [*stage_rows(MEM), ('bit', 'launch', f'{MEM}.launch'), ('bit', 'd_req_valid_o', f'{MEM}.d_req_valid_o'),
              ('bit', 'd_req_ready_i', f'{MEM}.d_req_ready_i'), ('bus', 'd_req_addr_o', f'{MEM}.d_req_addr_o', HEX, held(f'{MEM}.d_req_valid_o')),
              ('bit', 'd_rsp_valid_i', f'{MEM}.d_rsp_valid_i'), ('retire', 'trace_o', MEM)],
     'trigger': lambda s, c: s(f'{MEM}.launch', c) and s(f'{MEM}.d_req_valid_o', c + 1) and not s(f'{MEM}.d_req_ready_i', c + 1),
     'before': 2, 'after': 8,
     'markers': [('reserve', lambda s, c: s(f'{MEM}.launch', c)), ('first valid', lambda s, c: s(f'{MEM}.d_req_valid_o', c)),
                 ('accept', lambda s, c: s(f'{MEM}.d_req_valid_o', c) and s(f'{MEM}.d_req_ready_i', c)),
                 ('response', lambda s, c: s(f'{MEM}.d_rsp_valid_i', c))],
     'requires': [('the offer waits at least one cycle for ready', lambda s, k: s(f'{MEM}.d_req_valid_o', k + 1) and not s(f'{MEM}.d_req_ready_i', k + 1)),
                  ('the offer is accepted exactly once', lambda s, k: sum(s(f'{MEM}.d_req_valid_o', c) and s(f'{MEM}.d_req_ready_i', c) for c in range(k, k + 9)) == 1)]},
    {'id': 'access-fault', 'guide': 'microcontroller/rtl/README.md', 'bench': 'memory-base', 'seed': 1,
     'title': 'precise load access fault from a no-effect error response',
     'rows': [*stage_rows(MEM), ('bit', 'd_req_valid_o', f'{MEM}.d_req_valid_o'), ('bit', 'd_req_ready_i', f'{MEM}.d_req_ready_i'),
              ('bus', 'd_req_addr_o', f'{MEM}.d_req_addr_o', HEX, held(f'{MEM}.d_req_valid_o')), ('bit', 'd_rsp_valid_i', f'{MEM}.d_rsp_valid_i'),
              ('bus', 'd_rsp_status_i', f'{MEM}.d_rsp_status_i', DEC, held(f'{MEM}.d_rsp_valid_i')), ('retire', 'trace_o', MEM),
              ('bit', 'redirect_valid_o', f'{MEM}.redirect_valid_o'), ('bus', 'mcause_o', f'{MEM}.mcause_o', HEX),
              ('bus', 'mepc_o', f'{MEM}.mepc_o', HEX), ('bus', 'mtval_o', f'{MEM}.mtval_o', HEX)],
     'trigger': lambda s, c: s(f'{MEM}.d_rsp_valid_i', c) and s(f'{MEM}.d_rsp_status_i', c), 'before': 9, 'after': 5,
     'markers': [('error response', lambda s, c: s(f'{MEM}.d_rsp_valid_i', c)), ('trap', lambda s, c: s(f'{MEM}.trace_o.trap', c) and s(f'{MEM}.trace_o.valid', c))],
     'traps': True,
     'requires': [('the trap records a load access fault', lambda s, k: s(f'{MEM}.mcause_o', k + 3) == 5),
                  ('mtval names the requested address', lambda s, k: s(f'{MEM}.mtval_o', k + 3) == s(f'{MEM}.d_req_addr_o', k - 1))]},
    {'id': 'csr-serialization', 'guide': 'microcontroller/rtl/README.md', 'bench': 'csr-control', 'seed': 1,
     'title': 'serialized CSR write: input closed until the ordered W commit',
     'rows': [*stage_rows(CSR), ('bit', 'in_valid_i', f'{CSR}.in_valid_i'), ('bit', 'in_ready_o', f'{CSR}.in_ready_o'),
              ('retire', 'trace_o', CSR), ('bus', 'mscratch_o', f'{CSR}.mscratch_o', HEX)],
     'trigger': lambda s, c: raw_at(CSR, 4, s, c) & 0x707f == 0x1073, 'before': 6, 'after': 5,
     'markers': [('CSR reaches W', lambda s, c: raw_at(CSR, 4, s, c) & 0x707f == 0x1073),
                 ('mscratch written', lambda s, c: s(f'{CSR}.mscratch_o', c) != s(f'{CSR}.mscratch_o', c - 1))],
     'requires': [('W holds the CSR for a preparation edge', lambda s, k: raw_at(CSR, 4, s, k + 1) == raw_at(CSR, 4, s, k)),
                  ('input stays closed while the CSR is in flight', lambda s, k: not any(s(f'{CSR}.in_ready_o', c) for c in range(k - 4, k + 2)))]},
    {'id': 'interrupt-entry', 'guide': 'microcontroller/rtl/README.md', 'bench': 'irq-control', 'seed': 1,
     'title': 'software interrupt entry after a CSR write enables MIE', 'cw': 52,
     'rows': [*stage_rows(IRQ), ('retire', 'trace_o', IRQ), ('bus', 'mstatus_o', f'{IRQ}.mstatus_o', HEX),
              ('bus', 'mip_o', f'{IRQ}.mip_o', HEX), ('bit', 'entry_pending_o', f'{IRQ}.entry_pending_o'),
              ('bit', 'irq_valid_o', f'{IRQ}.irq_valid_o'), ('bus', 'irq_cause_o', f'{IRQ}.irq_cause_o', HEX, held(f'{IRQ}.irq_valid_o')),
              ('bus', 'mepc_o', f'{IRQ}.mepc_o', HEX), ('bus', 'redirect_pc_o', f'{IRQ}.redirect_pc_o', HEX, held(f'{IRQ}.redirect_valid_o'))],
     'trigger': lambda s, c: s(f'{IRQ}.irq_valid_o', c), 'before': 10, 'after': 0,
     'markers': [('MIE set', lambda s, c: s(f'{IRQ}.mstatus_o', c) & 8), ('entry', lambda s, c: s(f'{IRQ}.irq_valid_o', c))],
     'requires': [('the cause is the machine software interrupt', lambda s, k: s(f'{IRQ}.irq_cause_o', k) == 0x80000003),
                  ('entry clears MIE and sets MPIE', lambda s, k: s(f'{IRQ}.mstatus_o', k) & 0x88 == 0x80),
                  ('mepc is the next instruction boundary', lambda s, k: s(f'{IRQ}.mepc_o', k) == s(f'{IRQ}.irq_pc_o', k))],
     'extra': [f'{IRQ}.redirect_valid_o', f'{IRQ}.irq_pc_o']},
    {'id': 'wfi-wake', 'guide': 'microcontroller/rtl/README.md', 'bench': 'irq-control', 'seed': 1,
     'title': 'WFI retires, the core idles, and a timer interrupt wakes it', 'cw': 52,
     'rows': [*stage_rows(IRQ), ('retire', 'trace_o', IRQ), ('bit', 'idle_o', f'{IRQ}.idle_o'), ('bus', 'mip_o', f'{IRQ}.mip_o', HEX),
              ('bit', 'irq_valid_o', f'{IRQ}.irq_valid_o'), ('bus', 'irq_cause_o', f'{IRQ}.irq_cause_o', HEX, held(f'{IRQ}.irq_valid_o')),
              ('bus', 'mepc_o', f'{IRQ}.mepc_o', HEX)],
     'trigger': lambda s, c: s(f'{IRQ}.idle_o', c) and s(f'{IRQ}.mip_o', c) & 0x80, 'before': 7, 'after': 2,
     'markers': [('idle', lambda s, c: s(f'{IRQ}.idle_o', c)), ('wake', lambda s, c: s(f'{IRQ}.idle_o', c - 1) and not s(f'{IRQ}.idle_o', c)),
                 ('entry', lambda s, c: s(f'{IRQ}.irq_valid_o', c))],
     'requires': [('the timer interrupt is taken', lambda s, k: s(f'{IRQ}.irq_cause_o', k + 2) == 0x80000007),
                  ('mepc follows the WFI', lambda s, k: s(f'{IRQ}.mepc_o', k + 2) == 0x34)]},
    {'id': 'divide-latency', 'guide': 'microcontroller/rtl/README.md', 'bench': 'muldiv-forwarded', 'seed': 1,
     'title': 'blocking divide: 33 clocks from accepted start to result-valid', 'cw': 18,
     'rows': [*stage_rows(MD), ('bit', 'md_start', f'{MD}.md_start'), ('bit', 'md_busy', f'{MD}.md_busy'),
              ('bit', 'md_valid', f'{MD}.md_valid'), ('bit', 'd_hazard', f'{MD}.d_hazard'), ('retire', 'trace_o', MD)],
     'trigger': lambda s, c: s(f'{MD}.md_start', c) and raw_at(MD, 2, s, c) & 0xfe00707f == 0x02004033 and s(f'{MD}.d_hazard', c + 2),
     'before': 3, 'after': 39,
     'markers': [('start accepted', lambda s, c: s(f'{MD}.md_start', c)), ('result valid', lambda s, c: s(f'{MD}.md_valid', c))],
     'requires': [('result-valid rises 33 edges after the accepting edge', lambda s, k: first(s, k, lambda s, c: s(f'{MD}.md_valid', c), 40) == k + 34),
                  ('the dependent instruction waits throughout', lambda s, k: all(s(f'{MD}.d_hazard', c) for c in range(k, k + 35)))]},
    {'id': 'fence-i', 'guide': 'microcontroller/rtl/README.md', 'bench': 'fence', 'seed': 1,
     'title': 'FENCE.I: redirect to PC+4, stale response dropped, fresh fetch generation',
     'rows': [*stage_rows(FEN), ('retire', 'trace_o', FEN), ('bit', 'redirect_valid_i', 'cpu5_fence_execution_tb.frontend.redirect_valid_i'),
              ('bit', 'discard_o', 'cpu5_fence_execution_tb.frontend.discard_o'),
              ('bus', 'generation_o', 'cpu5_fence_execution_tb.frontend.generation_o', DEC),
              ('bit', 'i_req_valid_o', 'cpu5_fence_execution_tb.frontend.i_req_valid_o'),
              ('bit', 'i_req_ready_i', 'cpu5_fence_execution_tb.frontend.i_req_ready_i'),
              ('bus', 'i_req_addr_o', 'cpu5_fence_execution_tb.frontend.i_req_addr_o', HEX, held('cpu5_fence_execution_tb.frontend.i_req_valid_o')),
              ('bit', 'i_rsp_valid_i', 'cpu5_fence_execution_tb.frontend.i_rsp_valid_i'),
              ('bit', 'drop_o', 'cpu5_fence_execution_tb.frontend.drop_o')],
     'search_from': lambda s: 4200,
     'trigger': lambda s, c: s('cpu5_fence_execution_tb.frontend.redirect_valid_i', c), 'before': 9, 'after': 8,
     'markers': [('fence.i retires', lambda s, c: s('cpu5_fence_execution_tb.frontend.redirect_valid_i', c)),
                 ('stale response dropped', lambda s, c: s('cpu5_fence_execution_tb.frontend.drop_o', c)),
                 ('fresh fetch', lambda s, c: s('cpu5_fence_execution_tb.frontend.i_req_valid_o', c) and
                  s('cpu5_fence_execution_tb.frontend.generation_o', c) != s('cpu5_fence_execution_tb.frontend.generation_o', c - 12))],
     'requires': [('W held FENCE.I before the redirect', lambda s, k: raw_at(FEN, 4, s, k - 1) == 0x0000100f),
                  ('the generation advances after the redirect', lambda s, k: s('cpu5_fence_execution_tb.frontend.generation_o', k + 1) != s('cpu5_fence_execution_tb.frontend.generation_o', k)),
                  ('an obsolete response is dropped', lambda s, k: first(s, k, lambda s, c: s('cpu5_fence_execution_tb.frontend.drop_o', c), 6) is not None)]},
    {'id': 'straddled-fetch', 'guide': 'microcontroller/rtl/README.md', 'bench': 'compressed', 'seed': 1,
     'title': 'mixed widths: a 32-bit instruction assembled from parcels of two words', 'cw': 22,
     'rows': [*stage_rows(CMP)[:3], ('bus', 'frontend pc', 'cpu5_compressed_execution_tb.frontend.pc', HEX),
              ('bus', 'frontend length', 'cpu5_compressed_execution_tb.frontend.length', DEC),
              ('bit', 'i_req_valid_o', 'cpu5_compressed_execution_tb.frontend.i_req_valid_o'),
              ('bit', 'i_req_ready_i', 'cpu5_compressed_execution_tb.frontend.i_req_ready_i'),
              ('bus', 'i_req_addr_o', 'cpu5_compressed_execution_tb.frontend.i_req_addr_o', HEX, held('cpu5_compressed_execution_tb.frontend.i_req_valid_o')),
              ('bus', 'i_req_parcels_o', 'cpu5_compressed_execution_tb.frontend.i_req_parcels_o', BIN2, held('cpu5_compressed_execution_tb.frontend.i_req_valid_o')),
              ('bit', 'i_rsp_valid_i', 'cpu5_compressed_execution_tb.frontend.i_rsp_valid_i'),
              ('bus', 'i_rsp_parcels_i', 'cpu5_compressed_execution_tb.frontend.i_rsp_parcels_i', BIN2, held('cpu5_compressed_execution_tb.frontend.i_rsp_valid_i')),
              ('bit', 'insn_valid_o', 'cpu5_compressed_execution_tb.frontend.insn_valid_o')],
     'trigger': lambda s, c: (s('cpu5_compressed_execution_tb.frontend.insn_valid_o', c) and
                              s('cpu5_compressed_execution_tb.frontend.pc', c) & 3 == 2 and s('cpu5_compressed_execution_tb.frontend.length', c) == 4),
     'before': 27, 'after': 2,
     'markers': [('high parcel', lambda s, c: s('cpu5_compressed_execution_tb.frontend.i_rsp_valid_i', c) and s('cpu5_compressed_execution_tb.frontend.i_rsp_parcels_i', c) == 2),
                 ('next word', lambda s, c: s('cpu5_compressed_execution_tb.frontend.i_rsp_valid_i', c) and s('cpu5_compressed_execution_tb.frontend.i_rsp_parcels_i', c) == 1 and s('cpu5_compressed_execution_tb.frontend.length', c) == 4),
                 ('delivered', lambda s, c: s('cpu5_compressed_execution_tb.frontend.insn_valid_o', c) and s('cpu5_compressed_execution_tb.frontend.length', c) == 4)],
     'requires': [('the instruction starts on a halfword boundary', lambda s, k: s('cpu5_compressed_execution_tb.frontend.pc', k) & 3 == 2),
                  ('only the low parcel of the next word is requested', lambda s, k: any(s('cpu5_compressed_execution_tb.frontend.i_req_valid_o', c) and
                   s('cpu5_compressed_execution_tb.frontend.i_req_parcels_o', c) == 1 and s('cpu5_compressed_execution_tb.frontend.i_req_addr_o', c) == (s('cpu5_compressed_execution_tb.frontend.pc', k) + 2) for c in range(k - 14, k)))]},
    {'id': 'debug-halt', 'guide': 'microcontroller/rtl/README.md', 'bench': 'debug-core', 'seed': 1,
     'title': 'halt request waits for an offered load, then halts before the trap handler', 'cw': 46,
     'rows': [*stage_rows(DBG), ('retire', 'trace_o', DBG), ('bit', 'debug_haltreq_i', f'{DBG}.debug_haltreq_i'),
              ('bit', 'd_req_valid_o', f'{DBG}.d_req_valid_o'), ('bit', 'd_req_ready_i', f'{DBG}.d_req_ready_i'),
              ('bit', 'd_rsp_valid_i', f'{DBG}.d_rsp_valid_i'), ('bus', 'd_rsp_status_i', f'{DBG}.d_rsp_status_i', DEC, held(f'{DBG}.d_rsp_valid_i')),
              ('bus', 'mcause_o', f'{DBG}.mcause_o', HEX), ('bit', 'debug_halted_o', f'{DBG}.debug_halted_o'),
              ('bus', 'debug_dpc_o', f'{DBG}.debug_dpc_o', HEX, held(f'{DBG}.debug_halted_o'))],
     'trigger': lambda s, c: (s(f'{DBG}.debug_haltreq_i', c) and not s(f'{DBG}.debug_haltreq_i', c - 1) and s(f'{DBG}.d_req_valid_o', c) and
                              not s(f'{DBG}.d_req_ready_i', c) and first(s, c, lambda s, k: s(f'{DBG}.d_req_ready_i', k), 4) is not None and
                              first(s, c, lambda s, k: s(f'{DBG}.debug_halted_o', k), 10) is not None),
     'before': 6, 'after': 8,
     'markers': [('halt requested', lambda s, c: s(f'{DBG}.debug_haltreq_i', c)),
                 ('accepted', lambda s, c: s(f'{DBG}.d_req_valid_o', c) and s(f'{DBG}.d_req_ready_i', c)),
                 ('halted', lambda s, c: s(f'{DBG}.debug_halted_o', c) and not s(f'{DBG}.debug_halted_o', c - 1))],
     'traps': True,
     'requires': [('the offered request stays valid after the halt request', lambda s, k: s(f'{DBG}.d_req_valid_o', k + 1)),
                  ('the halt reports the trap handler as dpc', lambda s, k: s(f'{DBG}.debug_dpc_o', k + 8) == s(f'{DBG}.mtvec_o', k + 8))],
     'extra': [f'{DBG}.mtvec_o']},
    {'id': 'hart-reset-request', 'guide': 'microcontroller/rtl/README.md', 'bench': 'memory-base', 'seed': 1,
     'title': 'hart reset aborts the instruction but keeps its offered request',
     'rows': [*stage_rows(MEM), ('bit', 'hart_reset_i', f'{MEM}.hart_reset_i'), ('bit', 'd_req_valid_o', f'{MEM}.d_req_valid_o'),
              ('bit', 'd_req_ready_i', f'{MEM}.d_req_ready_i'), ('bus', 'd_req_addr_o', f'{MEM}.d_req_addr_o', HEX, held(f'{MEM}.d_req_valid_o')),
              ('bit', 'd_rsp_valid_i', f'{MEM}.d_rsp_valid_i'), ('bit', 'mem_busy_o', f'{MEM}.mem_busy_o'),
              ('bit', 'in_ready_o', f'{MEM}.in_ready_o')],
     'trigger': lambda s, c: s(f'{MEM}.hart_reset_i', c) and s(f'{MEM}.d_req_valid_o', c) and not s(f'{MEM}.d_req_ready_i', c),
     'before': 6, 'after': 8,
     'markers': [('hart reset', lambda s, c: s(f'{MEM}.hart_reset_i', c)),
                 ('accepted', lambda s, c: s(f'{MEM}.d_req_valid_o', c) and s(f'{MEM}.d_req_ready_i', c)),
                 ('response', lambda s, c: s(f'{MEM}.d_rsp_valid_i', c)),
                 ('input reopens', lambda s, c: s(f'{MEM}.in_ready_o', c) and not s(f'{MEM}.mem_busy_o', c))],
     'kills': True,
     'requires': [('the reset removes every instruction token', lambda s, k: s(f'{MEM}.stage_valid_o', k + 1) == 0),
                  ('the request is still offered after the reset', lambda s, k: s(f'{MEM}.d_req_valid_o', k + 1)),
                  ('no new instruction enters before the response', lambda s, k: not any(s(f'{MEM}.in_ready_o', c) for c in range(k, first(s, k, lambda s, c: s(f'{MEM}.d_rsp_valid_i', c), 20) + 1)))]},
    {'id': 'fabric-ownership', 'guide': 'microcontroller/memory/README.md', 'bench': 'local-fabric', 'seed': 1,
     'title': 'local fabric MMIO write: owned offer, one effect, held response', 'cw': 26,
     'rows': [('bit', 'd_req_valid_i', f'{FAB}.d_req_valid_i'), ('bit', 'd_req_ready_o', f'{FAB}.d_req_ready_o'),
              ('bus', 'd_req_addr_i', f'{FAB}.d_req_addr_i', HEX, held(f'{FAB}.d_req_valid_i')),
              ('bus', 'd_req_wdata_i', f'{FAB}.d_req_wdata_i', HEX, held(f'{FAB}.d_req_valid_i')),
              ('bus', 'd_req_tag_i', f'{FAB}.d_req_tag_i', HEX, held(f'{FAB}.d_req_valid_i')),
              ('bit', 'owned', f'{FAB}.d_owned_q'), ('bit', 'accepted', f'{FAB}.d_accepted_q'),
              ('bit', 'status_write_o', f'{FAB}.status_write_o'), ('bus', 'status_o', f'{FAB}.status_o', HEX),
              ('bit', 'd_rsp_valid_o', f'{FAB}.d_rsp_valid_o'), ('bit', 'd_rsp_ready_i', f'{FAB}.d_rsp_ready_i'),
              ('bus', 'd_rsp_tag_o', f'{FAB}.d_rsp_tag_o', HEX, held(f'{FAB}.d_rsp_valid_o'))],
     'trigger': lambda s, c: (s(f'{FAB}.d_req_valid_i', c) and not s(f'{FAB}.d_req_valid_i', c - 1) and
                              s(f'{FAB}.d_req_write_i', c) and s(f'{FAB}.d_req_addr_i', c) == 0x40000000),
     'before': 1, 'after': 25,
     'markers': [('first valid', lambda s, c: s(f'{FAB}.d_req_valid_i', c)),
                 ('accept', lambda s, c: s(f'{FAB}.d_req_valid_i', c) and s(f'{FAB}.d_req_ready_o', c)),
                 ('effect', lambda s, c: s(f'{FAB}.status_write_o', c)),
                 ('response', lambda s, c: s(f'{FAB}.d_rsp_valid_o', c)),
                 ('consumed', lambda s, c: s(f'{FAB}.d_rsp_valid_o', c) and s(f'{FAB}.d_rsp_ready_i', c))],
     'requires': [('the payload stays stable while the offer waits', lambda s, k: len({(s(f'{FAB}.d_req_addr_i', c), s(f'{FAB}.d_req_wdata_i', c), s(f'{FAB}.d_req_tag_i', c))
                                                                                     for c in range(k, first(s, k - 1, lambda s, c: s(f'{FAB}.d_req_ready_o', c), 20) + 1)}) == 1),
                  ('the status effect happens once', lambda s, k: sum(s(f'{FAB}.status_write_o', c) for c in range(k, k + 25)) == 1),
                  ('the response is held while not consumed', lambda s, k: any(s(f'{FAB}.d_rsp_valid_o', c) and not s(f'{FAB}.d_rsp_ready_i', c) for c in range(k, k + 25)))],
     'extra': [f'{FAB}.d_req_write_i']},
    {'id': 'notification-counter', 'guide': 'microcontroller/memory/README.md', 'bench': 'irq-platform', 'seed': 1,
     'title': 'counted notifications: empty acknowledge rejected, saturation and sticky overflow', 'cw': 46,
     'rows': [('bit', 'system_reset_i', f'{NOTE}.system_reset_i'), ('bit', 'notification_i', f'{NOTE}.notification_i'),
              ('bit', 'command_i', f'{NOTE}.command_i'), ('bit', 'write_i', f'{NOTE}.write_i'),
              ('bus', 'addr_i', f'{NOTE}.addr_i', HEX, held(f'{NOTE}.command_i')), ('bit', 'error_o', f'{NOTE}.error_o'),
              ('bus', 'notification_count_o', f'{NOTE}.notification_count_o', DEC), ('bit', 'overflow_o', f'{NOTE}.overflow_o')],
     'trigger': lambda s, c: s(f'{NOTE}.overflow_o', c) and not s(f'{NOTE}.overflow_o', c - 1), 'before': 8, 'after': 6,
     'markers': [('empty acknowledge', lambda s, c: s(f'{NOTE}.error_o', c) and s(f'{NOTE}.addr_i', c) == 0x40001020),
                 ('full', lambda s, c: s(f'{NOTE}.notification_count_o', c) == 4), ('overflow', lambda s, c: s(f'{NOTE}.overflow_o', c))],
     'requires': [('this platform instance holds four notifications', lambda s, k: s(f'{NOTE}.notification_count_o', k) == 4),
                  ('the rejected acknowledge does not lose its coincident arrival', lambda s, k: any(s(f'{NOTE}.error_o', c) and s(f'{NOTE}.notification_i', c) and
                   s(f'{NOTE}.notification_count_o', c + 1) == s(f'{NOTE}.notification_count_o', c) + 1 for c in range(k - 8, k))),
                  ('overflow stays set', lambda s, k: all(s(f'{NOTE}.overflow_o', c) for c in range(k, k + 7)))]},
]


class Sampler:
    """give figure conditions indexed access to values sampled before each rising clock edge."""

    def __init__(self, samples, cycles):
        """keep sampled columns and the number of captured clock periods."""
        self.samples, self.n = samples, cycles

    def __call__(self, name, cycle):
        """return a sampled value, treating positions outside the capture as zero."""
        # an unloaded name is a figure definition error.
        if name not in self.samples:
            raise KeyError(f'signal not loaded for this figure: {name}')
        return self.samples[name][cycle] if 0 <= cycle < self.n else 0


class Recorder:
    """wrap a sampler and remember which signals a condition reads."""

    def __init__(self, sampler):
        """start with an empty set of read signal names."""
        self.sampler, self.names = sampler, set()

    def __call__(self, name, cycle):
        """record the signal name and return its sampled value."""
        self.names.add(name)
        return self.sampler(name, cycle)


def digest(path):
    """return the SHA-256 digest of one file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log, cwd):
    """run one tool command, retaining its combined output."""
    result = subprocess.run([str(part) for part in command], cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False, timeout=1800)
    log.write_text('$ ' + ' '.join(str(part) for part in command) + '\n' + result.stdout)
    return result.returncode, result.stdout


def build(key, build_root, verilator, cache):
    """compile one bench with tracing and a bound dump module, reusing an earlier build."""
    # a bench is compiled once per invocation.
    if key in cache:
        return cache[key]
    bench = BENCHES[key]
    directory = build_root / key
    directory.mkdir(parents=True)
    bind = directory / 'cpu5_wave_bind.sv'
    bind.write_text(f'// attach the dump module to the bench top.\nbind {bench["top"]} cpu5_wave_dump wave_dump ();\n')
    command = [verilator, '--binary', '--timing', '--assert', '-Wall', '-j', '2', '-CFLAGS', '-O0',
               '-Imicrocontroller/rtl', '--trace', '--trace-structs', '--top-module', bench['top'],
               '--Mdir', directory / 'obj', *[f'-G{name}={value}' for name, value in bench['params'].items()],
               *bench['sources'], TESTS + 'cpu5_wave_dump.sv', bind]
    code, text = execute(command, directory / 'build.log', ROOT)
    # traced builds keep the bench's own rule that no HDL warning is accepted.
    if code or '%Warning' in text:
        raise RuntimeError(f'{key} build failed: {directory / "build.log"}')
    cache[key] = (directory, command)
    return cache[key]


def simulate(figure, build_root, verilator, cache, runs):
    """run a figure's bench once per seed and plusarg set, requiring its normal pass marker."""
    bench = BENCHES[figure['bench']]
    directory, build_command = build(figure['bench'], build_root, verilator, cache)
    label = '-'.join([f's{figure["seed"]}', *[flag.strip('+') for flag in figure.get('plusargs', [])]])
    # identical runs share one dump.
    if (figure['bench'], label) in runs:
        return runs[(figure['bench'], label)]
    dump = directory / f'{label}.vcd'
    command = [directory / 'obj' / f'V{bench["top"]}', '+verilator+seed+1']
    # unseeded benches keep their runner's exact invocation.
    if bench['seeded']:
        command.append(f'+seed={figure["seed"]}')
    command += [*figure.get('plusargs', []), f'+wave={dump}']
    # the run directory receives any bench side files instead of the checkout.
    code, text = execute(command, directory / f'{label}.log', directory)
    marker = next((line for line in text.splitlines() if line.startswith(bench['pass'])), None)
    # a figure is drawn only from a run that reached its normal terminal check.
    if code or marker is None:
        raise RuntimeError(f'{figure["bench"]} run {label} did not pass: {directory / (label + ".log")}')
    runs[(figure['bench'], label)] = {'dump': dump, 'pass': marker, 'build': build_command, 'run': command}
    return runs[(figure['bench'], label)]


def needed(figure):
    """list every signal a figure samples."""
    names = {CLOCKS[figure['bench']]}
    # each row kind reads its own signals.
    for row in figure['rows']:
        # stage rows read validity, identity, instruction bytes and kills.
        if row[0] == 'stage':
            token = f'{row[2]}.stage_token_o[{row[3]}]'
            names |= {f'{row[2]}.stage_valid_o', f'{row[2]}.kill_valid_o', f'{token}.uid', f'{token}.p.pc',
                      f'{token}.p.raw', f'{token}.p.length', f'{token}.p.op', f'{token}.p.raw_valid'}
        # retirement rows read the terminal trace record.
        elif row[0] == 'retire':
            names |= {f'{row[2]}.trace_o.{field}' for field in ('valid', 'trap', 'uid', 'packet.pc')}
        # value rows name their signal and any qualifying valid bit.
        else:
            names |= {row[2], *row[4:5]}
    names |= set(figure.get('extra', []))
    return names


def label_for(s, prefix, index, cycle):
    """name the instruction held by one stage token."""
    token = f'{prefix}.stage_token_o[{index}]'
    op, length = s(f'{token}.p.op', cycle), s(f'{token}.p.length', cycle)
    complete = s(f'{token}.p.raw_valid', cycle) == (0x3 if length == 2 else 0xf)
    # complete original bytes travel with the token after D normalizes its operation.
    if complete and (op in RAW_OPS or s(f'{token}.p.raw', cycle)):
        return wave.disassemble(s(f'{token}.p.raw', cycle), s(f'{token}.p.pc', cycle), length)
    return OPS[op] if op < len(OPS) else f'op{op}'


def declared(info, name):
    """return a signal name with the bit range its dump declares."""
    return name + info[name]['range']


def traces(figure, info):
    """list a figure's gtkwave traces as display format, alias and declared dump name."""
    out, seen = [('bit', 'clk', declared(info, CLOCKS[figure['bench']]))], set()
    # each figure row maps onto one or more gtkwave traces.
    for row in figure['rows']:
        # the first stage row of a controller adds its validity vector and, where relevant, its kill report.
        if row[0] == 'stage' and row[2] not in seen:
            seen.add(row[2])
            out.append(('bin', 'valid W M X D F', declared(info, f'{row[2]}.stage_valid_o')))
            # figures about discarded work also show the registered kill report.
            if figure.get('kills'):
                out.append(('bin', 'kill W M X D F', declared(info, f'{row[2]}.kill_valid_o')))
        # each stage row shows the address of the instruction the stage holds.
        if row[0] == 'stage':
            out.append(('hex', f'{row[1]} pc', declared(info, f'{row[2]}.stage_token_o[{row[3]}].p.pc')))
        # the registered terminal trace record shows each retirement or trap and its address.
        elif row[0] == 'retire':
            out.append(('bit', 'trace valid', declared(info, f'{row[2]}.trace_o.valid')))
            # trap figures also show the trap flag of the trace record.
            if figure.get('traps'):
                out.append(('bit', 'trace trap', declared(info, f'{row[2]}.trace_o.trap')))
            out.append(('hex', 'trace pc', declared(info, f'{row[2]}.trace_o.packet.pc')))
        # single bits keep their row label as the alias.
        elif row[0] == 'bit':
            out.append(('bit', row[1], declared(info, row[2])))
        # values use the display format the row requests.
        else:
            out.append((row[3], row[1], declared(info, row[2])))
    return out


def program(figure, s, start, end):
    """list the instructions held by the stage rows in a window, oldest first, for the manifest."""
    listing, seen = [], set()
    # instructions are recorded in order of first appearance, scanning from W back to F.
    for cycle in range(start, end):
        # every valid stage contributes its instruction once.
        for row in reversed(figure['rows']):
            # only stage rows hold instruction identities.
            if row[0] == 'stage' and (s(f'{row[2]}.stage_valid_o', cycle) >> row[3]) & 1:
                uid = s(f'{row[2]}.stage_token_o[{row[3]}].uid', cycle)
                # repeated sightings of one instruction are skipped.
                if uid not in seen:
                    seen.add(uid)
                    listing.append({'pc': f"0x{s(f'{row[2]}.stage_token_o[{row[3]}].p.pc', cycle):x}",
                                    'instruction': label_for(s, row[2], row[3], cycle)})
    return listing


def portable(command, build_root):
    """record a command without machine-specific checkout or build-directory prefixes."""
    return [str(part).replace(str(build_root), '<build>').replace(str(ROOT) + '/', '') for part in command]


def produce(figure, build_root, verilator, cache, runs):
    """simulate, sample and check one figure, and describe the gtkwave view that shows it."""
    run = simulate(figure, build_root, verilator, cache, runs)
    info, timescale = wave.parse_vcd(run['dump'], needed(figure))
    edges = wave.rising_edges(info[CLOCKS[figure['bench']]]['changes'])
    period = edges[-1] - edges[-2]
    times = edges[1:] + [edges[-1] + period]
    s = Sampler({name: wave.sample(data['changes'], times) for name, data in info.items()}, len(edges))
    first = figure.get('search_from', lambda s: 0)(s)
    trigger = next((c for c in range(first, s.n) if figure['trigger'](s, c)), None)
    # a missing trigger means the bench no longer exercises this mechanism.
    if trigger is None:
        raise RuntimeError(f'{figure["id"]}: trigger not found')
    start, end = max(0, trigger - figure['before']), min(s.n, trigger + figure['after'] + 1)
    # every stated property of the window must still hold before the figure is exported.
    for text, check in figure.get('requires', []):
        # a failed property stops publication of a contradicted caption.
        if not check(s, trigger):
            raise RuntimeError(f'{figure["id"]}: requirement failed: {text}')
    markers, after = [], start
    # markers name events in order; each search starts at the previous marker's cycle.
    for letter, (label, condition) in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', figure.get('markers', [])):
        hit = next((c for c in range(after, end) if condition(s, c)), None)
        # an absent event is a figure error, not an omitted label.
        if hit is None:
            raise RuntimeError(f'{figure["id"]}: marker {label!r} not found')
        reader = Recorder(s)
        condition(reader, hit)
        # the marker sits where the signals its condition reads last changed within that clock period.
        moment = max((time for name in reader.names for time, _ in info[name]['changes'] if edges[hit] <= time < times[hit]),
                     default=edges[hit])
        markers.append({'name': letter, 'label': label, 'cycle': hit, 'time': moment})
        after = hit
    view = {'dump': run['dump'], 'traces': traces(figure, info), 'markers': markers,
            # half a clock period of padding keeps the first and last cycles inside gtkwave's rounded zoom.
            'times': [edges[start] - period // 2, (edges[end] if end < len(edges) else edges[-1] + period) + period // 2]}
    return view, {'trigger_cycle': trigger, 'window_cycles': [start, end - 1], 'timescale': timescale,
                  'window_times': view['times'], 'markers': markers,
                  'traces': [{'alias': alias, 'signal': name} for _, alias, name in view['traces']],
                  'instructions': program(figure, s, start, end),
                  'pass': run['pass'], 'build_command': portable(run['build'], build_root),
                  'run_command': portable(run['run'], build_root)}


def tool(command, names):
    """return a tool's version line and the digest of its first existing executable below the launcher."""
    launcher = Path(shutil.which(command) or command).resolve()
    version = next((line.strip() for line in subprocess.run([str(launcher), '--version'], text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout.splitlines()
                    if line.strip()), '')
    binary = next((path for name in names for path in [launcher.parent.parent / name] if path.is_file()), launcher)
    return {'version': version, 'executable': binary.relative_to(launcher.parent.parent).as_posix(),
            'executable_sha256': digest(binary)}


def prepare_views(selected, build_root, verilator):
    """check the selected figures and write save files that gtkwave opens by hand, without any export."""
    cache, runs = {}, {}
    # each view is written as soon as its figure has been built, simulated and checked.
    for figure in selected:
        view, record = produce(figure, build_root, verilator, cache, runs)
        directory, name = view['dump'].parent, figure['id']
        (directory / f'{name}.vcd').symlink_to(view['dump'].name)
        wave.view_file(directory / f'{name}.gtkw', f'{name}.vcd', view['traces'], *view['times'],
                       [(m['name'], m['time'], m['label']) for m in view['markers']])
        print(f'VIEW {name} cycles={record["window_cycles"][0]}-{record["window_cycles"][1]} '
              f'{directory / (name + ".gtkw")}', flush=True)
    print(f'VIEWS_PASS figures={len(selected)} build={build_root}')


def main():
    """parse arguments, then list the figures, prepare views or export figures with their manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--gtkwave', default='gtkwave')
    parser.add_argument('--build', type=Path, help='new build directory; required unless --list is given')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/waveforms')
    parser.add_argument('--figure', action='append', default=[], metavar='NAME',
                        help='export only this figure and leave the manifest alone; repeatable')
    parser.add_argument('--view', action='append', default=[], metavar='NAME',
                        help='check this figure and write its gtkwave save file with zoom and markers, '
                             'without export; repeatable')
    parser.add_argument('--list', action='store_true', help='print the figure names and exit')
    args = parser.parse_args()
    # listing names the available figures without running anything.
    if args.list:
        print('\n'.join(f'{figure["id"]}: {figure["title"]}' for figure in FIGURES))
        return
    # every other mode builds benches and needs somewhere to put them.
    if args.build is None:
        parser.error('the following arguments are required: --build')
    # a view never reaches the export, so one run cannot do both.
    if args.view and args.figure:
        parser.error('--view and --figure cannot be combined')
    names = args.view or args.figure
    selected = [figure for figure in FIGURES if not names or figure['id'] in names]
    unknown = set(names) - {figure['id'] for figure in FIGURES}
    # unknown names indicate a mistyped request.
    if unknown:
        raise SystemExit('unknown figure: ' + ', '.join(sorted(unknown)))
    args.build.mkdir(parents=True, exist_ok=False)
    # a view run stops here: no display server, no gtkwave process and no published file.
    if args.view:
        prepare_views(selected, args.build.resolve(), args.verilator)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    rcfile = args.build.resolve() / 'gtkwaverc'
    # a private rc file keeps a personal gtkwave configuration out of the exported images.
    rcfile.write_text('splash_disable 1\n')
    cache, runs, records, views = {}, {}, [], []
    # every bench is built, simulated and checked before any display is opened.
    for figure in selected:
        views.append((figure, *produce(figure, args.build.resolve(), args.verilator, cache, runs)))
    # one private X server serves every gtkwave export in this run.
    with wave.x_display(1920, 1080) as (display, server):
        # figures are exported in declaration order.
        for figure, view, record in views:
            directory, name = view['dump'].parent, figure['id']
            (directory / f'{name}.vcd').symlink_to(view['dump'].name)
            px = round(figure.get('cw', 34) * 1.6)
            signals = max(170, 8 * max(len(alias) for _, alias, _ in view['traces']) + 40)
            width = min(1900, 120 + signals + px * (record['window_cycles'][1] - record['window_cycles'][0] + 1))
            wave.save_file(directory / f'{name}.gtkw', f'{name}.vcd', view['traces'], width, signals)
            wave.grab_script(directory / f'{name}.tcl', *view['times'],
                             [(m['name'], m['time'], m['label']) for m in view['markers']], f'{name}.png')
            image, command = wave.export(args.gtkwave, directory, f'{name}.vcd', f'{name}.gtkw', f'{name}.tcl',
                                         f'{name}.png', display, rcfile, directory / f'{name}-gtkwave.log')
            target = args.output / image.name
            shutil.copyfile(image, target)
            records.append({'id': name, 'title': figure['title'], 'guide': figure['guide'],
                            'bench': figure['bench'], 'top': BENCHES[figure['bench']]['top'],
                            'parameters': BENCHES[figure['bench']]['params'], 'seed': figure['seed'],
                            'plusargs': figure.get('plusargs', []), 'image': target.name,
                            'image_sha256': digest(target), **record,
                            'gtkwave_command': portable(command, args.build.resolve())})
            print(f'WAVEFORM {name} cycles={record["window_cycles"][0]}-{record["window_cycles"][1]} {target}', flush=True)
    sources = sorted({path for figure in selected for path in BENCHES[figure['bench']]['sources']} |
                     {TESTS + 'cpu5_wave_dump.sv', TESTS + 'waveform_render.py', TESTS + 'run_waveforms.py',
                      RTL + 'cpu5_datapath_defs.svh'})
    manifest = {'schema': 'CPU5-WAVEFORM-FIGURES-2', 'date': datetime.date.today().isoformat(),
                'scope': 'gtkwave screen grabs of cycle windows from passing directed-bench runs of the recorded '
                         'sources; a figure illustrates one run and is not a qualification result',
                'tools': {'verilator': tool(args.verilator, ['libexec/verilator_bin', 'bin/verilator_bin']),
                          'gtkwave': tool(args.gtkwave, ['libexec/gtkwave']), 'display_server': server},
                'source_sha256': {path: digest(ROOT / path) for path in sources}, 'figures': records}
    # a partial selection records only the figures it produced.
    if not args.figure:
        (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'WAVEFORMS_PASS figures={len(records)} output={args.output}')


# the module can be imported by exploration scripts without running figures.
if __name__ == '__main__':
    main()
