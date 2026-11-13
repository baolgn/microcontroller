# Microcontroller

A learning project for building and understanding a five-stage RISC-V CPU in SystemVerilog. The work explores instruction decoding, pipeline ownership, forwarding, precise exceptions, machine interrupts, compressed instructions, integer multiply/divide and hardware debug. Small modules, directed tests and execution traces make each mechanism independently inspectable.

The repository contains the CPU and the local memory, timer, firmware, boot and verification support needed to exercise it. The local firmware profiles are `RV32I_Zicsr_Zifencei` and `RV32IMC_Zicsr_Zifencei`, both in machine mode. The I-only firmware profile omits M and C; it still requires CSR and instruction-synchronization support. This is an educational implementation under development: complete architectural qualification and physical FPGA operation remain unverified. The local FPGA image and the separate debug simulation are distinct configurations.

## [Installation](docs/README.md#installation)

Install [Git](https://git-scm.com/downloads) and clone the repository. Run commands from its root unless a component guide states otherwise. Use checkout, tool and build paths containing only ASCII letters, digits, `/`, `.`, `_` and `-`; the acceptance runner rejects other characters.

```sh
git clone https://github.com/baolgn/microcontroller.git
cd microcontroller
```

### Ubuntu and Debian

Install the host utilities and simulator, then follow the [development setup](docs/README.md#installation) for the tools required by the selected check. These packages do not install the pinned FPGA or RISC-V toolchains. The guide also provides [Fedora and Arch commands](docs/README.md#fedora-and-arch-linux).

```sh
sudo apt update
sudo apt install git python3 python3-venv build-essential ripgrep zlib1g-dev \
  curl ca-certificates tar gzip verilator
```

### Windows

For the Linux build workflows, run this command in **Administrator PowerShell** using [Microsoft's WSL installation procedure](https://learn.microsoft.com/en-us/windows/wsl/install):

```powershell
wsl --install -d Ubuntu
```

Restart if requested and finish Ubuntu's account setup. Open Ubuntu from PowerShell:

```powershell
wsl --distribution Ubuntu
```

Run the Ubuntu package and clone commands inside that Linux shell, keeping the checkout in its Linux filesystem. The [Windows setup](docs/README.md#windows-powershell-and-wsl) also explains native source access and the distinction between Windows and Linux tools.

### macOS

Install the command-line compiler tools and complete the installer:

```sh
xcode-select --install
```

After installing [Homebrew](https://brew.sh/), run these commands in Terminal for the initial Verilator simulation:

```sh
brew install git python3 make ripgrep verilator
export PATH="$(brew --prefix make)/libexec/gnubin:$PATH"
```

The [macOS setup](docs/README.md#macos-terminal) includes version checks. Full workflows that require Linux binaries run on an [Ubuntu x86-64 VM or remote host](docs/README.md#linux-only-toolchains); an ARM Ubuntu guest does not satisfy the pinned x86-64 bundle. Native macOS, WSL and VM runs must establish their own results.

Start with the [fetch-buffer simulation](docs/README.md#first-simulation-check), then follow the [test guide](microcontroller/tests/README.md). The [firmware](microcontroller/firmware/README.md), [FPGA synthesis](microcontroller/synth/README.md) and [programming](microcontroller/programming/README.md) guides describe their separate workflows.

## [CPU implementation](microcontroller/README.md)

The CPU uses F, D, X, M and W stages with ordered retirement. Instruction metadata travels with its owner through stalls and redirects. Register and CSR updates commit at retirement, while memory requests receive ordering permission before launch. Diagnostic, interlocked and forwarded configurations support comparison of correctness before performance.

The [RTL guide](microcontroller/rtl/README.md) explains the implemented modules and diagrams. The supporting local platform supplies boot ROM, instruction and data RAM, a timer and diagnostic output. Debug Module and JTAG transport tests use a separate wrapper; the programmable FPGA image does not automatically include that debug path.

## [Development and verification](docs/README.md)

The development guide connects setup, first simulations and broader CPU checks. Verification includes directed corner cases, reproducible random programs, retirement-level comparison, independent memory-effect checks and formal properties under stated environmental assumptions. Architectural tests complement these checks; they do not establish correctness by themselves.

The [verification guide](microcontroller/verification/README.md) records the limits of the ACT4/Sail integration and scoped proofs. Historical routing and simulation observations are distinct from fresh results for this source tree and from measurements on a physical board. The [initial publication checks](docs/validation.json) and [follow-up audit checks](docs/audit-validation.json) identify their separate source snapshots and selected regressions.

## [FPGA and firmware tools](microcontroller/qualification/README.md)

The selected FPGA target is ULX3S v3.1.7 D&M with an LFE5U-85F-6BG381C. The open-source development flow uses Verilator, GTKWave, Yosys, nextpnr, SymbiYosys, RISC-V GCC/binutils/GDB, ACT4/Sail, OpenOCD and openFPGALoader where supported. Exact versions, installation paths and required capabilities belong to the relevant component guides.

FPGA configuration and CPU firmware updates are separate operations. Programming, flash readback, power-cycle boot and recovery must be verified on the actual board before claiming hardware qualification.

The [changelog](CHANGELOG.md) records CPU development milestones and subsequent changes.
