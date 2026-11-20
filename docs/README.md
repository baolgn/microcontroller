# Development documentation

This guide supports a learning project in CPU architecture, RTL design and verification. Begin with an independently testable block, inspect its expected behavior, and then move to pipeline, memory, exception and firmware integration. The [CPU guide](../microcontroller/README.md) describes the implementation; the [changelog](../CHANGELOG.md) records its development chronology.

## Installation

Use Python 3.11 or newer. Simulation additionally needs Verilator, a C++ compiler and Make. Synthesis, formal verification, firmware and debugger workflows have separate dependencies. Run commands from the repository root. Use checkout, tool and build paths containing only ASCII letters, digits, `/`, `.`, `_` and `-`; the acceptance runner enforces this alphabet, including the resolved tool paths.

Shell blocks marked `sh` run in Linux or macOS. On Windows, run those blocks inside Ubuntu under WSL; `powershell` blocks run in PowerShell. A tool's installed version is not proof that a test passed with it.

### Ubuntu and Debian

```sh
sudo apt update
sudo apt install git python3 python3-venv build-essential ripgrep zlib1g-dev \
  curl ca-certificates tar gzip verilator
```

These packages support the first simulation. They do not install the pinned FPGA or RISC-V toolchains. Check the installed versions before proceeding:

```sh
python3 --version
verilator --version
make --version
c++ --version
git clone https://github.com/baolgn/microcontroller.git
cd microcontroller
```

### Fedora and Arch Linux

On Fedora:

```sh
sudo dnf install git python3 gcc gcc-c++ make ripgrep zlib-ng-compat-devel \
  curl ca-certificates tar gzip verilator
```

On Arch Linux, update the system and install the build tools together:

```sh
sudo pacman -Syu --needed base-devel git python ripgrep zlib \
  curl ca-certificates tar gzip verilator
```

Use the Linux commands below on either distribution. Their package versions require their own successful checks; Ubuntu observations do not qualify these installations.

### Windows PowerShell and WSL

Follow [Microsoft's WSL installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install). In **Administrator PowerShell**:

```powershell
wsl --install -d Ubuntu
```

Restart if requested and complete Ubuntu's first-launch account setup. In PowerShell, inspect the installation and open its Linux shell:

```powershell
wsl --list --verbose
wsl --distribution Ubuntu
```

Run the Ubuntu package commands inside Ubuntu. Keep the checkout in the Linux filesystem:

```sh
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone https://github.com/baolgn/microcontroller.git
cd microcontroller
uname -m
```

For native Windows source access, install [Git for Windows](https://git-scm.com/install/windows) and Python. Native Python is useful for source inspection, but the documented build and integration commands run in the Linux environment. Windows Python does not provide the Linux compiler, simulator, FPGA toolchain or debugger services. The Linux-oriented integration runners require the WSL environment described above. USB programming and graphical waveform inspection also require device/display access and separate validation.

### macOS Terminal

Install Apple's command-line compiler tools and finish the installer:

```sh
xcode-select --install
```

Install [Homebrew](https://brew.sh/) using its official instructions, then install the native simulation tools:

```sh
brew install git python3 make ripgrep verilator
export PATH="$(brew --prefix make)/libexec/gnubin:$PATH"
python3 --version
make --version
c++ --version
verilator --version
git clone https://github.com/baolgn/microcontroller.git
cd microcontroller
```

Repeat the PATH command in each simulation terminal, or add it to the shell configuration. It makes Homebrew's GNU Make available to child builds as `make`. Native macOS results have not been qualified; the first simulation must pass on the selected installation.

### Linux-only toolchains

Full FPGA qualification, ACT4/Sail campaigns and several integrated runners use Linux x86-64 executables, Linux libraries or Linux process interfaces. On Windows x86-64, use Ubuntu under WSL 2. On macOS, use an Ubuntu **x86-64** VM or remote host for these workflows. An ARM Ubuntu guest cannot run the pinned x86-64 bundle natively.

An existing Ubuntu host can be reached from macOS Terminal or Windows PowerShell:

```sh
ssh developer@ubuntu-host
```

Replace that example account and hostname with your own. Inside the Ubuntu shell, check `uname -m`, install the Ubuntu prerequisites above, and clone a separate working copy. Remote access alone does not provide USB or graphical display access.

The [tool qualification guide](../microcontroller/qualification/README.md) describes the exact FPGA bundle and fixture. The [firmware guide](../microcontroller/firmware/README.md) describes the compiler profile. Some legacy runners require particular installation paths; inspect their documented options and defaults rather than assuming that similarly named system tools are interchangeable.

## First simulation check

The fetch-buffer runner needs only Verilator and the host build tools. It checks instruction parcel assembly and an intentionally corrupted observation. The intentional detector failure must be recognized by its named comparison; an unrelated compile error or crash is not a successful negative test.

From the repository root in Linux, WSL Ubuntu or macOS:

```sh
(
  set -eu
  cpu_build=$(mktemp -d "${TMPDIR:-/tmp}/cpu5-fetch-buffer.XXXXXX")
  python3 -B microcontroller/tests/run_fetch_buffer.py \
    --verilator "$(command -v verilator)" \
    --build "$cpu_build"
  printf 'Results: %s\n' "$cpu_build/results.json"
)
```

Success requires exit zero and `expected_result: true` for both entries in `results.json`. The build and execution logs remain in the printed directory. The result covers this module and its stated test cases; it is not complete CPU qualification.

For the decoder, immediate generator, ALU and shifter, run the separate datapath checks:

```sh
(
  set -eu
  cpu_build=$(mktemp -d "${TMPDIR:-/tmp}/cpu5-datapath.XXXXXX")
  make -C microcontroller/tests datapath \
    VERILATOR="$(command -v verilator)" BUILD_ROOT="$cpu_build"
  printf 'Results: %s\n' "$cpu_build/datapath"
)
```

This target uses deterministic operand seeds and named failure detectors. The [test guide](../microcontroller/tests/README.md) explains the remaining module and integration runners.

## Firmware build settings

Build every object and the supplied private runtime for the selected CPU profile and the ILP32 ABI. The firmware build script selects explicit versions: `rv32i2p1_zicsr2p0_zifencei2p0` for its I-only profile, or `rv32i2p1_m2p0_c2p0_zicsr2p0_zifencei2p0` for IMC. The I-only profile includes machine CSR and instruction-synchronization support; it must not be compiled as IMC.

Inspect the current arguments before running a build:

```sh
python3 -B microcontroller/firmware/build.py --help
```

Pass a compiler prefix from the qualified RISC-V installation and a new output directory. The [firmware guide](../microcontroller/firmware/README.md) covers startup, stack, initialized data, BSS, trap context saving and generated-instruction checks. The [programming guide](../microcontroller/programming/README.md) separates image creation from device operations.

## Verification progression

Use [module simulations](../microcontroller/tests/README.md) before [integrated verification](../microcontroller/verification/README.md). Check pipeline stalls and flushes, operand dependencies, memory effects, exceptions and interrupts before interpreting firmware output. Apply [formal checks](../microcontroller/verification/formal/README.md) with their explicit bounds and assumptions. Configure [ACT4/Sail](../microcontroller/verification/act4/README.md) for the actual ISA and memory map.

The [waveform figures](../microcontroller/tests/README.md#waveform-figures) show selected cycle windows from passing bench runs: pipeline overlap, hazards, branches, memory ownership, traps, CSR serialization, interrupts, fences, compressed fetch and debug halt. Their [manifest](waveforms/manifest.json) binds each figure to its bench, seed, window, tool and source hashes. Regenerate them after changing the sources they depict.

The standalone publication omits historical generated evidence bundles. Old measurements describe their original configurations, and current source changes require new runs. Keep tool versions, source hashes, seeds, logs, traces and expected failures together in a fresh output directory. Several legacy runners have fixed output paths; inspect their options or use the [isolated acceptance runner](../microcontroller/release/README.md) before running an aggregate campaign.

Physical FPGA programming, cold boot, flash readback, recovery and debug probe operation remain separate acceptance checks. Simulation, synthesis and a routed timing report do not substitute for those observations.
