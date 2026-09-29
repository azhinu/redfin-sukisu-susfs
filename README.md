# redfin-kernel

A custom kernel for Google Pixel 5 (`redfin`) with SukiSU Ultra and SUSFS,
for Evolution X 16.0 and Google stock Android.

**AI Generated Content:** This project contains AI-generated code and documentation.

## Manual build

Use Linux/macOS with Git, Python 3.10+, and Docker with Compose installed.
Run the commands below in Bash.

```sh
git clone --recurse-submodules https://github.com/azhinu/redfin-sukisu-susfs.git
cd redfin-sukisu-susfs
```

### Evolution X 16.0

Place `EvolutionX-16.0-20260207-redfin-11.5.3-Official.zip` in
`rom/evolution/`, then download the matching kernel sources and build:

```sh
source configs/evolution-kernel.env
git clone --no-checkout "$EVOLUTION_KERNEL_URL" rom/evolution/kernel
git -C rom/evolution/kernel checkout "$EVOLUTION_KERNEL_REVISION"
./scripts/build-evolution.sh
```

The output is saved to `artifacts/evolution-susfs-v420/`.
Use it with the Evolution X release listed above.

### Google stock Android

```sh
./scripts/build-susfs.sh
```

The output is saved to `artifacts/susfs-sukisu-v420/`.
The stock build has not been tested on a device running stock Android.

Both builds produce `boot.img` and `AnyKernel-redfin-sukisu.zip`.
