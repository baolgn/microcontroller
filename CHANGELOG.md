# Changelog

Dates follow the maintainer's CPU milestone chronology. They do not change Git commit dates or test-run timestamps. Historical simulation and routing observations describe the configurations tested at the time; generated evidence bundles are not included in this standalone source publication.

## 2026-11-13

Prepared the standalone CPU learning repository, standardized module names to `cpu5_*`, and organized the documentation around CPU implementation, local firmware, verification, FPGA tools and programming. Limited the published scope to the CPU and its supporting local platform. Rewrote the main README and installation guide with Linux, Windows/WSL and macOS instructions, and expanded the changelog into descriptions of the implemented behavior.

Validated eight CPU unit-test families, the firmware/image/local-platform/boot-recovery suites, three debug-wrapper seeds and the release helper fixtures. The [publication checks](docs/validation.json) bind the exercised code to its source hashes and retain the limits of those checks.

## 2026-11-10

Assessed CPU execution under concurrent firmware work, interrupt handling, delayed memory service, debug halt and reset. The checks distinguished an instruction's architectural completion from its bus effects and required outstanding requests to retain ownership through stalls and control events. The CPU-only source retains [control-event](microcontroller/tests/run_control_events.py), [interrupt](microcontroller/tests/run_irq_control.py), [debug](microcontroller/tests/run_debug_core.py) and [local-platform](microcontroller/tests/run_local_platform.py) verification. Those suites cover their declared cases; they do not establish unrestricted worst-case execution time.

Added release tooling for isolated acceptance, dependency installation and deterministic packaging. [acceptance.py](microcontroller/release/acceptance.py) stages source before running selected suites; [bootstrap_tools.py](microcontroller/release/bootstrap_tools.py) checks supplied dependency identities; [package_release.py](microcontroller/release/package_release.py) validates archive paths, inventory, permissions and hashes. Release assessment separated software results from incomplete architectural comparisons, timing limits and physical qualification. Archive integrity is not proof that every CPU requirement passes.

## 2026-11-09

Separated volatile FPGA configuration, persistent configuration storage and CPU firmware updates. [image.py](microcontroller/programming/image.py) validates application-bank metadata and contents, while [program_board.py](microcontroller/programming/program_board.py) prepares device operations with target identity and readback checks. [cpu5_spi_boot.sv](microcontroller/rtl/cpu5_spi_boot.sv) validates stored firmware, and [cpu5_boot_soc.sv](microcontroller/rtl/cpu5_boot_soc.sv) releases the CPU after instruction-memory loading. Normal updates preserve bank A and replace bank B; simulated damaged-bank, empty-bank and failed-application recovery remain distinct from physical flash and power-cycle qualification.

## 2026-11-08

Implemented halt, resume, reset-halt, abstract register access and single-step through [cpu5_debug_module.sv](microcontroller/rtl/cpu5_debug_module.sv), [cpu5_debug_transport.sv](microcontroller/rtl/cpu5_debug_transport.sv) and [cpu5_debug_system.sv](microcontroller/rtl/cpu5_debug_system.sv). Halt drains launched memory work, and resume must not repeat MMIO effects. Debug 1.0 stepping handles a trapping instruction by updating machine trap state and stopping before handler execution. [run_debug_remote.py](microcontroller/tests/run_debug_remote.py) exercises OpenOCD/GDB through a simulated transport; physical probe operation remains unqualified.

Combined directed execution, deterministic random programs, retirement comparison, ACT4 signatures and scoped formal checks. [comparison.py](microcontroller/verification/execution/comparison.py) checks execution records independently. [cpu5_pipeline_formal.sv](microcontroller/verification/formal/cpu5_pipeline_formal.sv), [cpu5_progress_admission_formal.sv](microcontroller/verification/formal/cpu5_progress_admission_formal.sv) and [cpu5_fetch_formal.sv](microcontroller/tests/cpu5_fetch_formal.sv) check selected ownership, retirement and progress properties under explicit bounds and service assumptions. The historical ACT4 campaign retained five capacity omissions and two comparison failures per timing seed, involving `mcause` policy and `timeh` applicability. This was not complete architectural qualification or a whole-core proof.

Connected the CPU to synchronous local memories and MMIO through [cpu5_soc.sv](microcontroller/rtl/cpu5_soc.sv) and [cpu5_local_fabric.sv](microcontroller/rtl/cpu5_local_fabric.sv). The platform supplies 8 KiB of ROM, 64 KiB of instruction RAM, 32 KiB of data RAM, a timer, retained interrupts and diagnostic output. [start.S](microcontroller/firmware/start.S) establishes the stack, initialized data and BSS; [trap.S](microcontroller/firmware/trap.S) saves the interrupted context. [build.py](microcontroller/firmware/build.py) compiles separate I-only and IMC firmware profiles with ILP32 and checks generated instructions. Local simulations exercised calls, arrays, arithmetic, interrupts and exception recovery.

Added FPGA clock/reset integration in [cpu5_ulx3s.sv](microcontroller/synth/fpga/cpu5_ulx3s.sv), UART output and board diagnostics in [cpu5_board_system.sv](microcontroller/rtl/cpu5_board_system.sv), and exact-target synthesis/routing through [run_fpga.py](microcontroller/synth/run_fpga.py). Local-memory changes enabled block RAM inference. The integrated 80 MHz target failed; the 25 MHz profile passed a guarded 27.7778 MHz routing constraint. The diagnostic handler took 845 clocks against an 800-clock allocation. These are historical routing and simulation observations, not physical board measurements or current-source timing qualification.

## 2026-11-07

Added all eight RV32M multiply, divide and remainder operations in [cpu5_muldiv.sv](microcontroller/rtl/cpu5_muldiv.sv). Blocking X-stage execution retains operation identity and holds completed results until consumption. Unit checks exercise mixed-sign high products, division by zero, signed overflow, quotient rounding, remainder signs and backpressure. Multiply and divide first assert result-valid two and 33 clocks after acceptance, respectively; downstream waiting adds to these arithmetic latencies.

Implemented RV32C classification, HINT handling and decompression in [cpu5_decompress.sv](microcontroller/rtl/cpu5_decompress.sv). Original instruction bits and length remain available through execution, compressed links use PC+2, and a second-parcel fetch fault retains the instruction-start PC. [run_decompress.py](microcontroller/tests/run_decompress.py) classifies all 65,536 halfword encodings; [run_compressed_execution.py](microcontroller/tests/run_compressed_execution.py) separately checks mixed-width programs, split instructions, redirects, stalls and faults.

Completed conservative FENCE ordering and configurable FENCE.I coordination between [cpu5_control.sv](microcontroller/rtl/cpu5_control.sv) and [cpu5_frontend.sv](microcontroller/rtl/cpu5_frontend.sv). Instruction synchronization waits for older data effects, invalidates buffered instructions and drains obsolete fetch responses through their existing owners. [run_fence_execution.py](microcontroller/tests/run_fence_execution.py) checks visibility and ordering. Another writer's completion must be established before the CPU performs instruction synchronization.

Completed RV32 machine-counter high/low accesses, rollover, inhibition, writes and retirement counting in [cpu5_csr.sv](microcontroller/rtl/cpu5_csr.sv). A successful compressed instruction counts once; a trapping instruction does not increment `minstret`. [cpu5_observe.sv](microcontroller/rtl/cpu5_observe.sv) supplies edge-aligned records, sequence/epoch identifiers and explicit overflow/capture-invalid state for independent replay. Machine counters do not imply implementation of the complete Zicntr extension.

## 2026-11-06

Integrated machine software, timer and external interrupts with retained platform events in [cpu5_irq_platform.sv](microcontroller/rtl/cpu5_irq_platform.sv). CPU control preserves masked pending events, re-evaluates eligibility after relevant CSR writes and MRET, and gives older synchronous exceptions priority. WFI suspends instruction admission while the timer and peripherals remain independently active. [run_irq_control.py](microcontroller/tests/run_irq_control.py) and [run_irq_fetch.py](microcontroller/tests/run_irq_fetch.py) exercise wakeup, entry boundaries and outstanding fetch ownership. Latency observations depend on each test's memory-service and pipeline assumptions.

## 2026-11-05

Completed machine CSR access, precise trap entry, MRET, ECALL and EBREAK in [cpu5_csr.sv](microcontroller/rtl/cpu5_csr.sv) and its [control integration](microcontroller/rtl/cpu5_control.sv). All six Zicsr operations implement their read/write suppression rules, including the distinction between selecting x0 and selecting a nonzero source-register index whose value is zero. The CSR behavior includes reset values, access permissions, legal writable values, `mconfigptr` and RV32 `mstatush`. [run_csr_control.py](microcontroller/tests/run_csr_control.py) checks encoded operations and trap transitions separately from standalone bank tests.

## 2026-11-04

Added all conditional branches, JAL and JALR in [cpu5_branch.sv](microcontroller/rtl/cpu5_branch.sv), including signed comparisons, correct link addresses and configuration-dependent instruction alignment. JALR clears target bit zero. X calculates the target, while W commits the redirect so older faults retain priority and a stalled branch cannot redirect repeatedly. [run_control_flow.py](microcontroller/tests/run_control_flow.py) checks the resulting instruction sequence and dependencies.

Added byte, halfword and word memory operations, little-endian byte enables, load extension, natural alignment and region permissions in [cpu5_lsu.sv](microcontroller/rtl/cpu5_lsu.sv) and the control request manager. A load to x0 still performs the access and can fault. One outstanding data transaction and ordered launch prevent younger effects from escaping an older fault. An uncertain response retains ownership rather than enabling automatic replay. [run_memory.py](microcontroller/tests/run_memory.py) checks architectural results and device effects independently.

Added newest-producer forwarding in [cpu5_forward.sv](microcontroller/rtl/cpu5_forward.sv) for ALU, branch, address and store-data operands. An unready newest match stalls the consumer instead of forwarding an older value; a load becomes a source only after successful completion. [run_base.py](microcontroller/tests/run_base.py) compares diagnostic, overlapping and forwarded execution across base instructions, traps and memory effects. This packet-driven milestone did not establish complete platform-level RV32I qualification.

## 2026-11-03

Implemented independently testable [decoder](microcontroller/rtl/cpu5_decoder.sv), [immediate generator](microcontroller/rtl/cpu5_immediate.sv), [ALU](microcontroller/rtl/cpu5_alu.sv), [barrel shifter](microcontroller/rtl/cpu5_shifter.sv) and [register file](microcontroller/rtl/cpu5_regfile.sv). Their tests cover legality, operand-use masks, signed/unsigned comparisons, wraparound and shift boundaries. The standalone register-file mapping evaluates flip-flops, distributed RAM and block RAM. Reads of x0 return zero, writes to x0 are ignored, and other registers have no assumed reset value. Read timing and write-through behavior are explicit.

Implemented tagged fetch ownership, execute-region checks and parcel assembly through [cpu5_fetch.sv](microcontroller/rtl/cpu5_fetch.sv), [cpu5_fetch_guard.sv](microcontroller/rtl/cpu5_fetch_guard.sv) and [cpu5_fetch_buffer.sv](microcontroller/rtl/cpu5_fetch_buffer.sv). The initial path assembles 32-bit instructions while carrying length metadata and the buffering needed for later compressed execution. Redirects discard stale responses and wrong-path faults. Sticky discard prevents an old response from becoming valid after generation wrap; peripheral regions are rejected before instruction-fetch launch.

## 2026-11-02

Established five-stage ownership in [cpu5_control.sv](microcontroller/rtl/cpu5_control.sv), with valid/ready transfers, stable stalls, reset and flush handling, ordered retirement, minimal trap state and a verification trace. [cpu5_control_pkg.sv](microcontroller/rtl/cpu5_control_pkg.sv) defines instruction and transaction metadata. A diagnostic configuration allows one instruction in flight while retaining F, D, X, M and W. Register and CSR updates occur at retirement; memory effects require separate ordering permission. Exposed requests retain an owner across hart reset until completion or established platform isolation.

## 2026-11-01

Specified instruction/data buses, interrupts, reset, debug and retirement information with explicit ownership. Once a request is presented, its valid and payload remain stable through acceptance, and its owner remains responsible for the response. Interrupt and debug entry are arbitrated before launch. Instruction metadata includes valid state, PC, original bits, length, operands, destination/result and fault information, with defined transfer, stall, flush and simultaneous-event behavior.

Prepared a minimal simulated platform with instruction memory, data memory, MMIO, a timer and deliberate error responders. Request acceptance and response latency vary independently. Side-effectful reads and writes expose duplicate device actions; deterministic seeds and independent bus-effect checking supplement architectural retirement comparison. The [verification fixtures](microcontroller/verification/README.md) distinguish lost or stale work, result errors and exception-ordering failures.

## 2026-10-31

Defined the implemented ISA and machine-state contract, keeping early I-only builds distinct from later IMC configurations. Pinned RV32I 2.1, M 2.0, C 2.0, Zicsr 2.0, Zifencei 2.0 and Machine ISA 1.13, with M-only execution, little-endian accesses and explicit alignment, reset, exception, interrupt, CSR and counter behavior. Unsupported instructions and unavailable CSR accesses require defined illegal-instruction behavior. [CPU documentation](microcontroller/rtl/README.md) separates configuration options from claims of complete architectural qualification.

Established measurable CPU budgets for instruction/data service, interrupt response, debug halt, blocking division, firmware execution, resources and clock frequency. Every deadline identifies its timing endpoints and memory/peripheral assumptions. Measured arithmetic latency, firmware handler cost and routed timing are separate observations; a finite tested maximum does not establish unrestricted worst-case execution time.

Selected an open-source Ubuntu development flow and the exact ULX3S v3.1.7 D&M / LFE5U-85F-6BG381C target. [Tool qualification](microcontroller/qualification/README.md) covers Verilator, GTKWave, Yosys with a suitable frontend, nextpnr/Trellis, SymbiYosys/solvers, RISC-V GCC/binutils/GDB, ACT4/Sail, OpenOCD and openFPGALoader. Primitive availability, simulation, synthesis, routing, bitstream generation and actual device programming are separate qualification gates; physical programming remains unverified.
