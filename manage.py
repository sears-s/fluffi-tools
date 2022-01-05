#!/usr/bin/env python3

import argparse
import re
import subprocess
import time

import requests

# Constants
N_MIN = 5
N_MAX = 8
SSH_SERVER_PREFIX = "worker"
WORKER_NAME_PREFIX = "fluffi-1021-"
WORKER_NAME_SUFFIX = "-Linux1"
FLUFFI_PATH_PREFIX = "/home/sears/fluffi"
GIT_URL = "https://github.com/sears-s/fluffi"
FUZZGOAT_PATH = "/home/sears/fluffi-tools/fuzzgoat"
ARCH = "x64"
PROXY_PORT = 8888
PROXIES = {
    "http": f"socks5h://127.0.0.1:{PROXY_PORT}",
    "https": f"socks5h://127.0.0.1:{PROXY_PORT}",
}
FLUFFI_URL = "http://web.fluffi:8880"
PM_URL = "http://pole.fluffi:8888/api/v2"
FUZZJOB_ID_REGEX = r'"/projects/archive/(\d+)"'
FUZZJOB_NAME_REGEX = r"<h1>([a-zA-Z0-9]+)</h1>"
FUZZJOB_NAME_PREFIX = "sears"


def main():
    # Create parser
    parser = argparse.ArgumentParser()
    parser.add_argument("command", type=str, help="clone, up, down, deploy, or all")
    parser.add_argument("-n", type=int, help=f"{N_MIN}-{N_MAX} or omit for all")
    args = parser.parse_args()

    # Check host
    if args.n and (args.n < N_MIN or args.n > N_MAX):
        print("Invalid host")
        exit(1)

    # Process command
    if args.command == "clone":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                clone(i)
        else:
            clone(args.n)
    elif args.command == "up":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                start_proxy(i)
                up(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            up(args.n)
            stop_proxy()
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                start_proxy(i)
                down(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            down(args.n)
            stop_proxy()
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                deploy(i)
        else:
            deploy(args.n)
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                start_proxy(i)
                down(i)
                deploy(i)
                up(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            down(args.n)
            deploy(args.n)
            up(args.n)
            stop_proxy()
    else:
        print("Invalid command")
        exit(1)


def clone(n):
    print(f"Cloning 1021-{n}...")

    # Init string
    fluffi_path = f"{FLUFFI_PATH_PREFIX}{n}"

    # Clone the repo and switch to branch
    subprocess.run(
        ["git", "clone", GIT_URL, fluffi_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "checkout", f"1021-{n}"],
        cwd=fluffi_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "lfs", "pull"],
        cwd=fluffi_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Prepare environment and compile dependencies
    subprocess.run(
        ["sudo", "./buildAll.sh", "PREPARE_ENV=TRUE", "WITH_DEPS=TRUE"],
        cwd=f"{fluffi_path}/build/ubuntu_based",
        check=True,
    )

    print(f"1021-{n} cloned")


def stop_proxy():
    subprocess.run(
        f"lsof -ti tcp:{PROXY_PORT} | xargs kill",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Stopped proxy")


def start_proxy(n):
    stop_proxy()
    subprocess.run(
        f"ssh {SSH_SERVER_PREFIX}{n} -D {PROXY_PORT} -N &",
        check=True,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    print("Started proxy")


# Wrapper for Fluffi requests in case of database connection failure
def fluffi_req(s, url, files=None):
    while True:
        if files is None:
            r = s.get(url)
        else:
            r = s.post(url, files=files)
        if "Error: Database connection failed" in r.text:
            time.sleep(0.25)
            continue
        return r


def manage_agents():
    s = requests.Session()
    s.proxies.update(PROXIES)
    s.auth = ("admin", "admin")
    print("Starting manage agents task...")
    r = s.post(f"{PM_URL}/project/1/periodic_task/3/execute/")
    history_id = r.json()["history_id"]
    time.sleep(0.5)
    while True:
        try:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
        except:
            time.sleep(0.5)
            continue
        if r.json()["status"] == "OK":
            break
        time.sleep(0.5)
    print("Manage agents success")


def down(n):
    print(f"Stopping 1021-{n}...")

    # Init string
    worker_name = f"{WORKER_NAME_PREFIX}{n}{WORKER_NAME_SUFFIX}"

    # Create session
    s = requests.Session()
    s.proxies.update(PROXIES)

    # Get fuzzjob ID
    r = fluffi_req(s, f"{FLUFFI_URL}/projects")
    try:
        fuzzjob_id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
    except:
        fuzzjob_id = -1  # no current fuzzjob
    print(f"Fuzzjob ID: {fuzzjob_id}")

    # Get fuzzjob name
    if fuzzjob_id != -1:
        r = fluffi_req(s, f"{FLUFFI_URL}/projects/view/{fuzzjob_id}")
        fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
        print(f"Fuzzjob name: {fuzzjob_name}")

    # Downturn GRE
    if fuzzjob_id != -1:
        print("Downturning GRE...")
        r = fluffi_req(
            s,
            f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
            {
                f"{worker_name}_tg": (None, 0),
                f"{worker_name}_tg_arch": (None, ARCH),
                f"{worker_name}_tr": (None, 0),
                f"{worker_name}_tr_arch": (None, ARCH),
                f"{worker_name}_te": (None, 0),
                f"{worker_name}_te_arch": (None, ARCH),
            },
        )
        if "Success!" not in r.text:
            print("Error downturning GRE")
            print(r.text)
            stop_proxy()
            exit(1)
        manage_agents()
        print("GRE downturned")

    # Downturn LM
    print("Downturning LM...")
    r = fluffi_req(
        s,
        f"{FLUFFI_URL}/systems/configureSystemInstances/{worker_name}",
        {
            "localManager_lm": (None, 0),
            "localManager_lm_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        print("Error downturning LM")
        print(r.text)
        stop_proxy()
        exit(1)
    manage_agents()
    print("LM downturned")

    # Kill the leftovers
    print("Killing leftovers...")
    subprocess.run(
        [
            "ssh",
            f"{SSH_SERVER_PREFIX}{n}",
            f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Killed leftovers")

    # Archive fuzzjob
    if fuzzjob_id != -1:
        print("Archiving fuzzjob...")
        fluffi_req(s, f"{FLUFFI_URL}/projects/archive/{fuzzjob_id}", {})
        while True:
            r = s.get(f"{FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(0.25)
        print("Archive success")

    print(f"1021-{n} stopped")


def deploy(n):
    print(f"Deploying 1021-{n}...")

    # Init strings
    fluffi_path = f"{FLUFFI_PATH_PREFIX}{n}"
    ssh_server = f"{SSH_SERVER_PREFIX}{n}"

    # Clean old build
    print("Cleaning old build...")
    subprocess.run(
        ["rm", "-rf", f"{fluffi_path}/core/x86-64"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Old build cleaned")

    # Compile new build
    print("Compiling new build...")
    subprocess.run(
        ["sudo", "./buildAll.sh"],
        cwd=f"{fluffi_path}/build/ubuntu_based",
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("New build compiled")

    # Zip, SCP, and unzip
    print("Transferring new build...")
    subprocess.run(
        ["zip", "-r", "fluffi.zip", "."],
        cwd=f"{fluffi_path}/core/x86-64/bin",
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "scp",
            f"{fluffi_path}/core/x86-64/bin/fluffi.zip",
            f"{ssh_server}:/home/fluffi_linux_user/fluffi/persistent/x64",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "ssh",
            f"{ssh_server}",
            "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("New build transferred")

    print(f"1021-{n} deployed")


def up(n):
    print(f"Starting 1021-{n}...")

    # Init string
    worker_name = f"{WORKER_NAME_PREFIX}{n}{WORKER_NAME_SUFFIX}"

    # Create session
    s = requests.Session()
    s.proxies.update(PROXIES)

    # Create new fuzzjob
    print("Creating new fuzzjob...")
    r = fluffi_req(
        s,
        f"{FLUFFI_URL}/projects/createProject",
        [
            ("name", (None, f"{FUZZJOB_NAME_PREFIX}{int(time.time())}")),
            ("subtype", (None, "X64_Lin_DynRioSingle")),
            ("generatorTypes", (None, 100)),  # RadamsaMutator
            ("generatorTypes", (None, 0)),  # AFLMutator
            ("generatorTypes", (None, 0)),  # CaRRoTMutator
            ("generatorTypes", (None, 0)),  # HonggfuzzMutator
            ("generatorTypes", (None, 0)),  # OedipusMutator
            ("generatorTypes", (None, 0)),  # ExternalMutator
            ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
            ("location", (None, f"1021-{n}")),
            (
                "targetCMDLine",
                (
                    None,
                    "/home/fluffi_linux_user/fluffi/persistent/SUT/fuzzgoat/fuzzgoat",
                ),
            ),
            ("option_module", (None, "hangeTimeout")),
            ("option_module_value", (None, 5000)),
            (
                "targetModulesOnCreate",
                ("fuzzgoat", open(f"{FUZZGOAT_PATH}/fuzzgoat", "rb")),
            ),
            ("targetFile", (None, "")),
            ("filename", ("seed", open(f"{FUZZGOAT_PATH}/seed", "rb"))),
            ("basicBlockFile", (None, "")),
        ],
    )
    if "Success" not in r.text:
        print("Error creating new fuzzjob")
        print(r.text)
        stop_proxy()
        exit(1)
    print("Fuzzjob created")

    # Get fuzzjob ID
    fuzzjob_id = int(r.url.split("/view/")[1])
    print(f"Fuzzjob ID: {fuzzjob_id}")

    # Get fuzzjob name
    fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
    print(f"Fuzzjob name: {fuzzjob_name}")

    # Upturn LM
    print("Upturning LM...")
    r = fluffi_req(
        s,
        f"{FLUFFI_URL}/systems/configureSystemInstances/{worker_name}",
        {
            "localManager_lm": (None, 1),
            "localManager_lm_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        print("Error upturning LM")
        print(r.text)
        stop_proxy()
        exit(1)
    manage_agents()
    print("LM upturned")

    # Upturn GRE
    print("Upturning GRE...")
    r = fluffi_req(
        s,
        f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
        {
            f"{worker_name}_tg": (None, 2),
            f"{worker_name}_tg_arch": (None, ARCH),
            f"{worker_name}_tr": (None, 10),
            f"{worker_name}_tr_arch": (None, ARCH),
            f"{worker_name}_te": (None, 10),
            f"{worker_name}_te_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        print("Error upturning GRE")
        print(r.text)
        stop_proxy()
        exit(1)
    manage_agents()
    print("GRE upturned")

    print(f"1021-{n} started")


if __name__ == "__main__":
    main()