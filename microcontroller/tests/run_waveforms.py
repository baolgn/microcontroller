#!/usr/bin/env python3
"""run traced simulation fixtures and render cycle-aligned waveform figures for the guides."""
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
HEX, DEC = (lambda v: f'{v:x}'), str
BIN2 = (lambda v: f'{v:02b}')
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
     'title': 'halt request waits for an offered load, then halts before the trap handler',
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
     'requires': [('the reset removes every instruction token', lambda s, k: s(f'{MEM}.stage_valid_o', k + 1) == 0),
                  ('the request is still offered after the reset', lambda s, k: s(f'{MEM}.d_req_valid_o', k + 1)),
                  ('no new instruction enters before the response', lambda s, k: not any(s(f'{MEM}.in_ready_o', c) for c in range(k, first(s, k, lambda s, c: s(f'{MEM}.d_rsp_valid_i', c), 20) + 1)))]},
    {'id': 'fabric-ownership', 'guide': 'microcontroller/memory/README.md', 'bench': 'local-fabric', 'seed': 1, 'listing': False,
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
    {'id': 'notification-counter', 'guide': 'microcontroller/memory/README.md', 'bench': 'irq-platform', 'seed': 1, 'listing': False,
     'title': 'counted notifications: empty acknowledge rejected, saturation and sticky overflow', 'cw': 30,
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
    bind.write_text(f'/* attach the dump module to the bench top. */\nbind {bench["top"]} cpu5_wave_dump wave_dump ();\n')
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
            names |= {f'{row[2]}.trace_o.{field}' for field in ('valid', 'trap', 'uid')}
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


def assemble(figure, s, start, end, edges):
    """convert sampled columns into renderer rows, colors and a program listing."""
    cycles = list(range(start, end))
    colors, legend, rows, killed = {}, [], [{'label': 'clk', 'kind': 'clock'}], set()
    # stage tokens are colored by instruction identity in order of first appearance, oldest stage first.
    for cycle in cycles:
        # every valid stage contributes its instruction once, from W back to F.
        for row in reversed(figure['rows']):
            # only stage rows define instruction identities.
            if row[0] == 'stage' and (s(f'{row[2]}.stage_valid_o', cycle) >> row[3]) & 1:
                uid = s(f'{row[2]}.stage_token_o[{row[3]}].uid', cycle)
                # the first sighting fixes the color and listing entry.
                if uid not in colors:
                    colors[uid] = len(colors) % 8
                    pc = s(f'{row[2]}.stage_token_o[{row[3]}].p.pc', cycle)
                    legend.append([colors[uid], f'{pc:08x}', label_for(s, row[2], row[3], cycle), uid])
                # a registered kill report on the next edge names this token.
                if (s(f'{row[2]}.kill_valid_o', cycle + 1) >> row[3]) & 1:
                    killed.add(uid)
    legend = [(color, address, text + ('  (killed)' if uid in killed else '')) for color, address, text, uid in legend]
    # every requested row becomes one renderer row.
    for row in figure['rows']:
        # stage rows show which instruction owns each stage.
        if row[0] == 'stage':
            _, name, prefix, index = row
            valid = [(s(f'{prefix}.stage_valid_o', c) >> index) & 1 for c in cycles]
            uids = [s(f'{prefix}.stage_token_o[{index}].uid', c) if v else None for c, v in zip(cycles, valid)]
            rows.append({'label': name, 'kind': 'bus', 'values': uids, 'idle': [not v for v in valid],
                         'texts': [label_for(s, prefix, index, c).split(' ')[0] if v else '' for c, v in zip(cycles, valid)],
                         'colors': [colors.get(uid) for uid in uids],
                         # registered kill reports follow the edge that discarded the token.
                         'kills': [bool((s(f'{prefix}.kill_valid_o', c + 1) >> index) & 1) and v for c, v in zip(cycles, valid)]})
        # retirement rows show each terminal disposition in its instruction color.
        elif row[0] == 'retire':
            _, name, prefix = row
            valid = [s(f'{prefix}.trace_o.valid', c) for c in cycles]
            uids = [s(f'{prefix}.trace_o.uid', c) if v else None for c, v in zip(cycles, valid)]
            texts = ['trap' if s(f'{prefix}.trace_o.trap', c) else 'ret' for c in cycles]
            rows.append({'label': name, 'kind': 'bus', 'values': [(u, t) for u, t in zip(uids, texts)],
                         'idle': [not v for v in valid], 'texts': texts, 'colors': [colors.get(uid) for uid in uids]})
        # one-bit rows draw a level.
        elif row[0] == 'bit':
            rows.append({'label': row[1], 'kind': 'bit', 'values': [s(row[2], c) & 1 for c in cycles]})
        # value rows draw labelled bus segments, hidden while their qualifying valid bit is low.
        else:
            _, name, path, fmt = row[:4]
            values = [s(path, c) for c in cycles]
            idle = [not s(row[4], c) if len(row) > 4 else False for c in cycles]
            rows.append({'label': name, 'kind': 'bus', 'values': values, 'idle': idle, 'texts': [fmt(v) for v in values]})
    markers, after = [], start
    # markers name events in order; each search starts at the previous marker's cycle.
    for label, condition in figure.get('markers', []):
        hit = next((c for c in range(after, end) if condition(s, c)), None)
        # an absent event is a figure error, not an omitted label.
        if hit is None:
            raise RuntimeError(f'{figure["id"]}: marker {label!r} not found')
        markers.append({'column': hit - start, 'label': label})
        after = hit
    return {'title': figure['title'], 'cw': figure.get('cw', 34), 'cycles': cycles, 'rows': rows,
            'markers': markers, 'legend': legend if figure.get('listing', True) and legend else [],
            'subtitle': ''}


def subtitle(figure, start, end):
    """describe the bench, profile, seed and captured cycle range."""
    bench = BENCHES[figure['bench']]
    params = ' '.join(f'{name}={value}' for name, value in bench['params'].items())
    seed = f' · seed {figure["seed"]}' if bench['seeded'] else ''
    plus = ' ' + ' '.join(figure['plusargs']) if figure.get('plusargs') else ''
    return f'{bench["top"]} {params}{seed}{plus} · clock cycles {start}-{end - 1}'.replace('  ', ' ')


def portable(command, build_root):
    """record a command without machine-specific checkout or build-directory prefixes."""
    return [str(part).replace(str(build_root), '<build>').replace(str(ROOT) + '/', '') for part in command]


def produce(figure, build_root, verilator, cache, runs):
    """simulate, sample, check and render one figure."""
    run = simulate(figure, build_root, verilator, cache, runs)
    info, timescale = wave.parse_vcd(run['dump'], needed(figure))
    edges = wave.rising_edges(info[CLOCKS[figure['bench']]]['changes'])
    times = edges[1:] + [edges[-1] + (edges[-1] - edges[-2])]
    s = Sampler({name: wave.sample(data['changes'], times) for name, data in info.items()}, len(edges))
    first = figure.get('search_from', lambda s: 0)(s)
    trigger = next((c for c in range(first, s.n) if figure['trigger'](s, c)), None)
    # a missing trigger means the bench no longer exercises this mechanism.
    if trigger is None:
        raise RuntimeError(f'{figure["id"]}: trigger not found')
    start, end = max(0, trigger - figure['before']), min(s.n, trigger + figure['after'] + 1)
    # every stated property of the window must still hold before the figure is drawn.
    for text, check in figure.get('requires', []):
        # a failed property stops publication of a contradicted caption.
        if not check(s, trigger):
            raise RuntimeError(f'{figure["id"]}: requirement failed: {text}')
    drawing = assemble(figure, s, start, end, edges)
    drawing['subtitle'] = subtitle(figure, start, end)
    return drawing, {'trigger_cycle': trigger, 'window_cycles': [start, end - 1], 'timescale': timescale,
                     'window_times': [edges[start], edges[end - 1]], 'signals': sorted(needed(figure)),
                     'pass': run['pass'], 'build_command': portable(run['build'], build_root),
                     'run_command': portable(run['run'], build_root)}


def main():
    """parse arguments, render the selected figures and write their manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/waveforms')
    parser.add_argument('--figure', action='append', default=[])
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    # listing names the available figures without running anything.
    if args.list:
        print('\n'.join(f'{figure["id"]}: {figure["title"]}' for figure in FIGURES))
        return
    selected = [figure for figure in FIGURES if not args.figure or figure['id'] in args.figure]
    unknown = set(args.figure) - {figure['id'] for figure in FIGURES}
    # unknown names indicate a mistyped request.
    if unknown:
        raise SystemExit('unknown figure: ' + ', '.join(sorted(unknown)))
    args.build.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([args.verilator, '--version'], text=True).strip()
    launcher = Path(shutil.which(args.verilator) or args.verilator).resolve()
    candidates = [launcher.parent.parent / 'libexec/verilator_bin', launcher.parent / 'verilator_bin']
    binary = next((path for path in candidates if path.is_file()), None)
    cache, runs, records = {}, {}, []
    # figures are produced in declaration order so shared runs are reused.
    for figure in selected:
        drawing, record = produce(figure, args.build.resolve(), args.verilator, cache, runs)
        svg = wave.render(drawing)
        target = args.output / f'{figure["id"]}.svg'
        target.write_text(svg)
        records.append({'id': figure['id'], 'title': figure['title'], 'guide': figure['guide'],
                        'bench': figure['bench'], 'top': BENCHES[figure['bench']]['top'],
                        'parameters': BENCHES[figure['bench']]['params'], 'seed': figure['seed'],
                        'plusargs': figure.get('plusargs', []), 'svg': target.name,
                        'svg_sha256': digest(target), **record})
        print(f'WAVEFORM {figure["id"]} cycles={record["window_cycles"][0]}-{record["window_cycles"][1]} {target}', flush=True)
    sources = sorted({path for figure in selected for path in BENCHES[figure['bench']]['sources']} |
                     {TESTS + 'cpu5_wave_dump.sv', TESTS + 'waveform_render.py', TESTS + 'run_waveforms.py',
                      RTL + 'cpu5_datapath_defs.svh'})
    manifest = {'schema': 'CPU5-WAVEFORM-FIGURES-1', 'date': datetime.date.today().isoformat(),
                'scope': 'documentation figures cropped from passing directed-bench runs of the recorded sources; '
                         'a figure illustrates one run and is not a qualification result',
                'tool': {'verilator': version, 'executable': binary.relative_to(launcher.parent.parent).as_posix() if binary else None,
                         'executable_sha256': digest(binary) if binary else None},
                'source_sha256': {path: digest(ROOT / path) for path in sources}, 'figures': records}
    # a partial selection records only the figures it produced.
    if not args.figure:
        (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'WAVEFORMS_PASS figures={len(records)} output={args.output}')


# the module can be imported by exploration scripts without running figures.
if __name__ == '__main__':
    main()
