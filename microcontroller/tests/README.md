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

The waveform figures in the [CPU overview](../README.md#pipeline), the [RTL guide](../rtl/README.md) and the [memory guide](../memory/README.md) are screenshots exported by GTKWave itself. [run_waveforms.py](run_waveforms.py) regenerates them. For each figure it repeats the owning runner's sources and parameters, adds Verilator `--trace --trace-structs` and binds [cpu5_wave_dump.sv](cpu5_wave_dump.sv) to the bench top. The bench must reach its normal pass marker. The runner then finds the figure's trigger event, checks the properties its caption states and writes a GTKWave save file and Tcl script that select the signals, display formats, aliases, zoom range and named event markers. GTKWave loads the dump and saves the image with its own Grab To File command; [waveform_render.py](waveform_render.py) only parses the dump, writes those inputs and runs GTKWave. If a changed source no longer reproduces a trigger, marker or stated property, the run stops instead of leaving a stale figure.

The export uses the pinned GTKWave 3.4.0, because the grab is driven through its Tcl interface, and a private X display: `Xvfb` when it is installed, otherwise a rootful `Xwayland` window inside a Wayland session. Every bench is built, simulated and checked before that display opens. Use a new build directory. The command rewrites `docs/waveforms/` and its [manifest](../../docs/waveforms/manifest.json), which records each figure's bench, parameters, seed, cycle window, markers, traces, instructions, commands, tool identities and source hashes:

```sh
python3 -B microcontroller/tests/run_waveforms.py \
  --verilator /tmp/cpu5-control-tools-20260301/oss-cad-suite/bin/verilator \
  --gtkwave /tmp/cpu5-control-tools-20260301/oss-cad-suite/bin/gtkwave \
  --build /tmp/cpu5-waveforms-new
```

`--list` prints the figure names and needs no other option; every other mode requires `--build`. Repeated `--figure NAME` options export a subset without rewriting the manifest. Each bench directory keeps the complete dump beside the figure's save file, so `gtkwave NAME.vcd NAME.gtkw` run in that directory reloads the figure's traces for unrestricted inspection. The zoom range and markers of an export exist only in its Tcl script. An [interactive view](#interactive-views) writes them into the save file instead.

Read the figures as follows:

- The time axis is simulation time in picoseconds, and each bench sets its own clock period. Registered values change at rising edges of `clk`.
- `valid W M X D F` and `kill W M X D F` hold one bit per stage, W on the left and F on the right. A `pc` row shows the address held by that stage; it reads zero while the stage is empty, so check its valid bit. The manifest lists the instructions at those addresses.
- `trace valid`, `trace trap` and `trace pc` come from the registered terminal trace record, so a retirement or trap appears one cycle after the edge that caused it. `kill W M X D F` is registered in the same way.
- Named markers sit on the clock edge of each event, and their labels match the captions.

Each figure illustrates one passing run of the sources and tools recorded in the manifest. It does not extend a result to other seeds or profiles and does not qualify hardware timing.

### Interactive views

Repeated `--view NAME` options prepare figures for GTKWave without exporting them. The runner builds, simulates and checks each named figure exactly as it does for an export, then stops before it starts a display server or GTKWave. In the bench directory below the build directory it links `NAME.vcd` to the complete dump and writes `NAME.gtkw` through `view_file()` in [waveform_render.py](waveform_render.py). Nothing under `docs/waveforms/` changes, and `--view` cannot be combined with `--figure`.

The save file selects the same traces, aliases and display formats as the export, and it also carries what the export passes through its Tcl script. `[timestart]` sets the left edge of the cycle window. The line that starts with `*` holds the zoom, an unset primary marker and the times of the 26 named markers, with `-1` for every unused one. One `[markername]` line per event marker holds its letter and label. GTKWave draws `2**-zoom` time units in every 200 pixels and keeps only the whole part of that count. `view_file()` therefore derives the count from the window length and the 1500-pixel window the view requests and rounds it up, because a count that GTKWave rounds down leaves the last cycles of a short window outside the wave pane. GTKWave reads these lines when it loads the save file, which leaves the window free to be scrolled, zoomed and extended with other signals of the dump.

This mode needs Verilator alone. It therefore also serves a host that cannot run the export, such as macOS, which has no `Xvfb`, and a GTKWave build without the Tcl interface, such as the 4.0 pre-release in the OSS CAD Suite for macOS. Use a new build directory:

```sh
python3 -B microcontroller/tests/run_waveforms.py \
  --verilator verilator \
  --build /tmp/cpu5-waveform-views-new \
  --view branch-redirect
```

Each `VIEW` line of the output names the save file it wrote, and `VIEWS_PASS` ends a run in which every named figure passed its checks. Open a view from its bench directory:

```sh
cd /tmp/cpu5-waveform-views-new/base-forwarded
gtkwave branch-redirect.vcd branch-redirect.gtkw
```

Figures of the same bench share one build within a run; `pipeline-overlap`, `load-use-stall` and `branch-redirect` all use `base-forwarded`. A view is not a published figure. It adds no manifest entry, and it shows what the sources and tools of that run produce, which need not be the tools the manifest records.

## Interpreting results

Retain exact source/tool identities, configurations, seeds, commands, summaries and failure traces. Successful arithmetic comparison does not prove memory ordering; retirement comparison alone can miss an extra MMIO read. Bus-effect, request-ownership and stale-response checks must remain independent.

Old complete campaign archives are not included in this repository. The changelog describes recorded development work without turning those records into fresh passes for renamed or changed sources. A new run must report its actual scope and leave unavailable dependencies, comparison failures, untested profiles and physical board checks explicit.
