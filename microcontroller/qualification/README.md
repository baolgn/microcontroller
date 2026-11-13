# Ubuntu tools and FPGA smoke checks

The selected target is **ULX3S v3.1.7 D&M**, **LFE5U-85F-6BG381C**. The open-source flow uses Verilator, Yosys, nextpnr-ecp5, Project Trellis, SymbiYosys, open solvers, GTKWave and openFPGALoader. Tool and device smoke checks are separate from CPU verification and physical programming.

The board has not been physically qualified. Package, speed grade, PCB revision, flash markings and programmer identity must be inspected on the actual assembly. Static support for an ECP5 family or an FPGA IDCODE does not establish all of those facts.

## Pinned tools

The selected [OSS CAD Suite Linux x64 2026-03-01](https://github.com/YosysHQ/oss-cad-suite-build/releases/tag/2026-03-01) archive is `oss-cad-suite-linux-x64-20260301.tgz`, 705,999,427 bytes, SHA-256 `3558d8cf5b88ba224cf8bae872f83bed11cffdde163b130412e20352029c85f1`.

| Tool | Pinned bundle identity |
| --- | --- |
| Verilator | `5.047 devel v5.046-19-ge9dd6eaaf (mod)` |
| Yosys | `0.62+112`, commit `687a36af388ec45018ab4bec8993f4c4daa5ccac` |
| nextpnr-ecp5 | `0.9-87-g858177d1` |
| Project Trellis | Commit `73bd411731808d80ead650bbc9840d9e02911e9e` |
| SymbiYosys | `v0.62-16-g4dabe8a` |
| Z3 | `4.15.5` |
| GTKWave | `3.4.0` |
| openFPGALoader | `v1.0.0`, bundled source identity `3ae5e5e4a5f055d12f6079616cb1ec1d67bf30f1` |

These identify reproducibility inputs, not a new execution result. Preserve modified/dirty version suffixes and record actual executable hashes. Bundle license notices identify component terms; this checkout does not declare a license for this repository's own code or resolve every dependency's redistribution terms.

The [smoke runner](run.py) checks the supplied archive and selected executable, primitive-model and device-database files before running its bounded checks. The nextpnr device database is embedded in its executable; Trellis supplies further ECP5 device and tile data. The full CPU flow additionally requires Yosys's compatible slang frontend and the matching [firmware compiler](../firmware/README.md).

## Ubuntu reproduction

Use Linux x86-64 and Python 3.11 or newer. Windows users can enter [Ubuntu WSL2](../../docs/README.md#windows-powershell-and-wsl); macOS users need an Ubuntu x86-64 VM or [remote host](../../docs/README.md#linux-only-toolchains) for the pinned Linux binaries. An ARM Linux guest does not run that bundle natively. These alternative environments require their own checks.

Install host prerequisites, then download and verify the exact archive before extraction. The example uses new directories and never programs hardware:

```sh
sudo apt update
sudo apt install python3 build-essential curl ca-certificates tar gzip
```

```sh
(
  set -eu
  mkdir /tmp/cpu5-control-tools-20260301
  cd /tmp/cpu5-control-tools-20260301
  curl --fail --location --output oss-cad-suite-linux-x64-20260301.tgz \
    https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-03-01/oss-cad-suite-linux-x64-20260301.tgz
  printf '%s\n' '3558d8cf5b88ba224cf8bae872f83bed11cffdde163b130412e20352029c85f1  oss-cad-suite-linux-x64-20260301.tgz' | sha256sum --check
  tar -xzf oss-cad-suite-linux-x64-20260301.tgz
)
```

From the repository root, with a graphical display available for GTKWave:

```sh
python3 microcontroller/qualification/run.py \
  --tools /tmp/cpu5-control-tools-20260301/oss-cad-suite \
  --archive /tmp/cpu5-control-tools-20260301/oss-cad-suite-linux-x64-20260301.tgz \
  --build /tmp/cpu5-tool-smoke-build-new \
  --output /tmp/cpu5-tool-smoke-results-new
```

Success requires exit zero, summary `host-tools-and-smoke-pass`, stable source hashes and all expected native results. A GUI display failure is a failed GUI check, not a waveform-inspection pass. The runner creates private cache/configuration paths and retains failed attempts.

## Scope of the fixture

The [portable fixture](smoke_core.sv) exercises a counter, 18×18 multiply and synchronous memory. [smoke_top.sv](smoke_top.sv) adds the selected clock and ECP5 primitive integration. The route selects `--85k --package CABGA381 --speed 6`, a 25 MHz reference on G2, and an 80 MHz smoke clock. It uses LUT/FF/carry logic, DP16KD block RAM, MULT18X18D, EHXPLLL, DCCA, I/O and USRMCLK primitives. This small fixture's clock target does not establish the complete CPU's timing.

The formal fixture requires a positive proof, a reachable cover and the expected failure of a deliberately false assertion. GTKWave must load the generated waveform and find its required signal categories. Programmer board/cable listings establish only static tool support. No USB write, flash readback or cold-boot observation occurs in the smoke runner.

The full CPU previously failed its 80 MHz routing target; the supported programmable build selects 25 MHz and a separate guarded route constraint. Re-run [synthesis](../synth/README.md) for changed CPU sources, and keep its results separate from this fixture.

## Physical programming boundary

The selected configuration path is ULX3S US1 with FT231XQ, VID:PID `0403:6015`, board identifier `ulx3s`, cable `ft231X` and expected FPGA IDCODE `0x41113043`. The selected flash is W25Q128JVSIQ. Verify those identities and the unique USB serial on the physical board before executing the [programming procedure](../programming/README.md).

The example inventory intentionally remains unverified. Use the programmable CPU bitstream and compatible firmware banks for CPU boot tests; the primitive smoke bitstream has no CPU or application ABI. Volatile configuration, persistent configuration, firmware update/readback and power-cycle execution are separate acceptance checks. CPU JTAG debug transport is also separate from FPGA configuration access.
