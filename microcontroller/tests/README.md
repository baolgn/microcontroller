# CPU and local-platform tests

This directory contains directed testbenches, simulator drivers, proof harnesses and Python orchestration. The RTL under test lives in [rtl/](../rtl/README.md). Each runner selects configurations, seeds, tool paths and expected outcomes; its SystemVerilog or C++ fixture supplies the actual stimulus and comparisons.

## First simulation

Install Python 3.11 or newer, Verilator, a C++ compiler and Make using the [host guide](../../docs/README.md). Run from the repository root and choose a fresh output directory:

```sh
python3 microcontroller/tests/run_fetch_buffer.py \
  --verilator verilator \
  --build /tmp/cpu5-fetch-buffer-new
```

The runner builds with assertions and warnings enabled, checks instruction assembly, and deliberately corrupts an observation to verify that the expected comparator fails. Success requires the positive terminal and the named negative failure; an unrelated crash cannot satisfy the negative control. Read `results.json`, `positive.log`, `raw_detector.log` and `build.log` together.

This command uses the Verilator on `PATH`. More extensive suites may require the [pinned OSS CAD tools](../qualification/README.md), the [RISC-V compiler](../firmware/README.md), formal solvers or architectural-reference dependencies. A distribution package with the same tool name does not inherit a result from a pinned build.

## Verification progression

| Area | Entry points | Purpose |
| --- | --- | --- |
| Datapath and registers | [Makefile](Makefile), [run_regfile.py](run_regfile.py), [run_forward.py](run_forward.py) | Decode legality, arithmetic, register behavior and newest-producer hazards. |
| Fetch and branches | [run_fetch.py](run_fetch.py), [run_fetch_buffer.py](run_fetch_buffer.py), [run_branch.py](run_branch.py), [run_control_flow.py](run_control_flow.py) | Stream ownership, alignment, redirects and dependent control flow. |
| Memory and CSRs | [run_memory.py](run_memory.py), [run_csr.py](run_csr.py), [run_csr_control.py](run_csr_control.py) | Physical effects, precise faults, CSR suppression and trap state. |
| Extensions and interrupts | [run_muldiv.py](run_muldiv.py), [run_decompress.py](run_decompress.py), [run_irq_control.py](run_irq_control.py), [run_irq_fetch.py](run_irq_fetch.py) | Arithmetic boundaries, all compressed encodings, pending events and safe entry. |
| Ordering and counters | [run_fence_execution.py](run_fence_execution.py), [run_counter_execution.py](run_counter_execution.py) | Instruction visibility and independent counter reconstruction. |
| Debug | [run_debug_core.py](run_debug_core.py), [run_debug_module.py](run_debug_module.py), [run_debug_system.py](run_debug_system.py), [run_debug_remote.py](run_debug_remote.py) | Core boundaries, DMI/JTAG, abstract access and actual debugger interoperability with simulation. |
| Firmware and boot | [run_local_platform.py](run_local_platform.py), [run_spi_boot.py](run_spi_boot.py), [run_programming.py](run_programming.py) | Compiled execution, stored-image validation and simulated recovery. |

The [Makefile](Makefile) provides shortcuts. Inspect the corresponding runner's `--help` when selecting tool paths or output directories. Some older runners select fixed Linux installations and write generated records below the checkout. Use a disposable checkout or the [isolated acceptance runner](../release/README.md) for aggregate work.

The [directed coordinator](../verification/run_directed.py) stages current sources and runs selected families with their negative controls. [Architectural/reference tests](../verification/README.md) and [formal checks](../verification/formal/README.md) supply different kinds of evidence. No one family establishes complete CPU correctness.

## Waveform figures

[run_waveforms.py](run_waveforms.py) regenerates the waveform figures in the [CPU overview](../README.md#pipeline), the [RTL guide](../rtl/README.md) and the [memory guide](../memory/README.md). For each figure it repeats the owning runner's sources and parameters, adds Verilator `--trace --trace-structs` and binds [cpu5_wave_dump.sv](cpu5_wave_dump.sv) to the bench top. The bench must reach its normal pass marker. The runner then crops a window around a defined trigger event, checks the properties its caption states and draws a self-contained SVG with [waveform_render.py](waveform_render.py). If a changed source no longer reproduces a trigger, marker or stated property, the run stops instead of leaving a stale figure.

Use a new build directory. The command rewrites `docs/waveforms/` and its [manifest](../../docs/waveforms/manifest.json), which records each figure's bench, parameters, seed, cycle window, commands, Verilator identity and source hashes:

```sh
python3 -B microcontroller/tests/run_waveforms.py \
  --verilator /tmp/cpu5-control-tools-20260301/oss-cad-suite/bin/verilator \
  --build /tmp/cpu5-waveforms-new
```

`--list` prints the figure names. Repeated `--figure NAME` options render a subset without rewriting the manifest. Each complete dump stays in the build directory beside its build and run logs, for example `/tmp/cpu5-waveforms-new/base-forwarded/s1.vcd`, and opens in GTKWave or Surfer for unrestricted inspection.

Read the figures as follows:

- Each column is one clock period, sampled just before the next rising edge. A valid/ready pair that is high in a column transfers at that column's right edge.
- Stage rows name the instruction that owns F, D, X, M or W. One color follows one instruction instance, and the listing below the figure gives its address and disassembly.
- A cross marks a token discarded at the following edge. `kill_valid_o` and `trace_o` are registered reports, so a kill or retirement record appears one cycle after the edge that caused it.
- Dashed markers name the first edge in the window where an event is visible. A bus value drawn as a flat line is not qualified by its valid signal in that cycle.

Each figure illustrates one passing run of the sources and tool recorded in the manifest. It does not extend a result to other seeds or profiles and does not qualify hardware timing.

## Interpreting results

Retain exact source/tool identities, configurations, seeds, commands, summaries and failure traces. Successful arithmetic comparison does not prove memory ordering; retirement comparison alone can miss an extra MMIO read. Bus-effect, request-ownership and stale-response checks must remain independent.

Old complete campaign archives are not included in this repository. The changelog describes recorded development work without turning those records into fresh passes for renamed or changed sources. A new run must report its actual scope and leave unavailable dependencies, comparison failures, untested profiles and physical board checks explicit.
