#!/usr/bin/env python3

import argparse
import logging
import os
import re

import fluffi

# Constants
N_MIN = 5
N_MAX = 8
EXP_BASE_DIR = os.path.expanduser("~/fluffi-tools/experiments")
FUZZBENCH_DIR = os.path.expanduser("~/fuzzbench")
FUZZBENCH_DIR_REMOTE = "fuzzbench/"
SEED_SIZE_LIMIT = 1 * 1024 * 1024  # 1MB, from Fuzzbench
NUM_TRIALS = 20

# Get logger
log = logging.getLogger("fluffi")


def main():
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("name", type=str, help="clone, up, down, deploy, or all")
    parser.add_argument("n", type=int, help=f"{N_MIN}-{N_MAX}")
    args = parser.parse_args()

    # Check host
    if args.n < N_MIN or args.n > N_MAX:
        print("Invalid host")
        exit(1)
    location = fluffi.LOCATION_FMT.format(args.n)

    # Create experiment directory
    exp_dir = os.path.join(EXP_BASE_DIR, args.name, location)
    os.makedirs(exp_dir, exist_ok=True)

    # Setup logging
    log.setLevel(logging.INFO)
    logging.basicConfig(
        filename=os.path.join(exp_dir, "experiment.log"),
        format=f"%(asctime)s %(levelname)s:{location}:%(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
    )

    # Connect to instance and ensure nothing is running
    inst = fluffi.Instance(args.n)
    inst.down()

    # Iterate over the Fuzzbench benchmarks
    for benchmark in os.listdir(FUZZBENCH_DIR):

        # Get the benchmark directory
        benchmark_dir = os.path.join(FUZZBENCH_DIR, benchmark)
        if not os.path.isdir(benchmark_dir):
            continue

        # Read the target
        with open(os.path.join(benchmark_dir, "target.txt")) as f:
            target_name = f.read()
        target_path = os.path.join(benchmark_dir, target_name)
        if not os.path.isfile(target_path):
            log.error(f"Benchmark {benchmark} has bad target")
            exit(1)
        log.debug(f"Benchmark {benchmark} has target {target_name}")
        with open(target_path, "rb") as f:
            data = f.read()
        module = (target_name, data)
        target_path_remote = os.path.join(FUZZBENCH_DIR_REMOTE, benchmark, target_name)
        library_path_remote = os.path.join(
            FUZZBENCH_DIR_REMOTE, benchmark, "shared_libs/"
        )

        # Read the seeds
        seeds_path = os.path.join(benchmark_dir, "seeds/")
        seeds = []
        if os.path.isdir(seeds_path):
            for seed in os.listdir(seeds_path):

                # Ignore seeds that aren't files or are too big
                seed_path = os.path.join(seeds_path, seed)
                if (
                    not os.path.isfile(seed_path)
                    or os.path.getsize(seed_path) > SEED_SIZE_LIMIT
                ):
                    continue

                # Read the file
                with open(seed_path, "rb") as f:
                    data = f.read()
                seeds.append((seed, data))
        log.debug(f"Got {len(seeds)} seeds for benchmark {benchmark}")

        # Create the experiment benchmark directory
        exp_benchmark_dir = os.path.join(exp_dir, benchmark)
        os.makedirs(exp_benchmark_dir, exist_ok=True)

        # Iterate over number of trials
        for i in range(1, NUM_TRIALS + 1):
            trial = i.zfill(2)

            # Check if trial already complete
            trial_dir = os.path.join(exp_benchmark_dir, trial)
            if os.path.isdir(trial_dir) and any(
                filename.endswith(".sql.gz") for filename in os.listdir(trial_dir)
            ):
                log.debug(
                    f"Trial {trial} for benchmark {benchmark} already complete, skipping"
                )
                continue
            os.makedirs(trial_dir, exist_ok=True)
            log.info(f"On trial {trial} for benchmark {benchmark}")

            # Run the experiment
            run_name = re.sub("[^0-9a-zA-Z]+", "", f"{benchmark}{trial}")
            inst.up(run_name, target_path_remote, module, seeds, library_path_remote)


if __name__ == "__main__":
    main()
