import logging
import os
import socket
import subprocess
import time

import pymysql

import util
from fuzzjob import Fuzzjob

# Constants
FLUFFI_PATH_FMT = os.path.expanduser("~/fluffi{}")
LOCATION_FMT = "1021-{}"
SSH_MASTER_FMT = "master{}"
SSH_WORKER_FMT = "worker{}"
WORKER_NAME_FMT = "fluffi-1021-{}-Linux1"
ARCH = "x64"
SUT_PATH = "/home/fluffi_linux_user/fluffi/persistent/SUT/"
FLUFFI_URL = "http://web.fluffi:8880"
PM_URL = "http://pole.fluffi:8888/api/v2"
DB_NAME = "fluffi_gm"

# Get logger
log = logging.getLogger("fluffi")


class Instance:
    def __init__(self, n):
        # Set members
        self.n = n
        self.fluffi_path = FLUFFI_PATH_FMT.format(self.n)
        self.location = LOCATION_FMT.format(self.n)
        self.worker_name = WORKER_NAME_FMT.format(self.n)

        # Create SSH connections
        self.ssh_master, self.sftp_master, self.master_addr = util.ssh_connect(
            SSH_MASTER_FMT.format(self.n)
        )
        self.ssh_worker, self.sftp_worker, _ = util.ssh_connect(
            SSH_WORKER_FMT.format(self.n)
        )

        # Connect to DB
        log.debug("Connecting to DB...")
        self.db = pymysql.connect(host=self.master_addr, user=DB_NAME, password=DB_NAME)
        log.debug("Connected to DB")

        # Check the proxy and initialize the session
        self.check_proxy()
        self.s = util.FaultTolerantSession(self)
        self.s.get(FLUFFI_URL)

    # Close SSH and DB sessions on destruction
    def __del__(self):
        self.sftp_master.close()
        self.sftp_worker.close()
        self.ssh_master.close()
        self.ssh_worker.close()
        self.db.close()

    ### High Level Functionality ###

    def deploy(self, clean=True):
        log.info("Deploying...")

        # Clean old build
        if clean:
            log.debug("Cleaning old build...")
            subprocess.run(
                ["rm", "-rf", f"{self.fluffi_path}/core/x86-64"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.debug("Old build cleaned")

        # Compile new build
        log.debug("Compiling new build...")
        subprocess.run(
            ["sudo", "./buildAll.sh"],
            cwd=f"{self.fluffi_path}/build/ubuntu_based",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("New build compiled")

        # Zip, SCP, and unzip
        log.debug("Transferring new build...")
        subprocess.run(
            ["zip", "-r", "fluffi.zip", "."],
            cwd=f"{self.fluffi_path}/core/x86-64/bin",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.sftp_worker.put(
            f"{self.fluffi_path}/core/x86-64/bin/fluffi.zip",
            f"/home/fluffi_linux_user/fluffi/persistent/{ARCH}/fluffi.zip",
        )
        self.ssh_worker.exec_command(
            "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
        )
        log.debug("New build transferred")

        log.info("Deployed")

    def up(self, name_prefix, target_path, module, seeds, library_path=None):
        log.info("Starting...")
        fuzzjob = self.new_fuzzjob(
            name_prefix, target_path, module, seeds, library_path
        )
        self.set_lm(1)
        fuzzjob.set_gre(2, 10, 10)
        log.info("Started")

    def down(self):
        log.info("Stopping...")
        fuzzjobs = self.get_fuzzjobs()
        for fuzzjob in fuzzjobs:
            fuzzjob.set_gre(0, 0, 0)
        self.set_lm(0)
        self.kill_leftover_agents()
        for fuzzjob in fuzzjobs:
            fuzzjob.archive()
        self.clear_dirs()
        log.info("Stopped")

    def all(self, name_prefix, target_path, module, seeds, library_path=None):
        self.down()
        self.deploy()
        self.up(name_prefix, target_path, module, seeds, library_path)

    ### SSH ###

    def check_proxy(self):
        # Check if the port is open
        log.debug("Checking proxy port...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((self.master_addr, util.PROXY_PORT))
            s.close()
            log.info("Proxy is open")
            return
        except Exception as e:
            log.warn(f"Failed connecting to proxy: {e}")

        # Start proxy server
        log.debug("Starting proxy...")
        _, stdout, stderr = self.ssh_master.exec_command(
            f"ssh localhost -D 0.0.0.0:{util.PROXY_PORT} -N -f"
        )
        if stdout.channel.recv_exit_status() != 0:
            log.error(f"Error starting proxy: {stderr.read()}")
            raise Exception("Error starting proxy")
        time.sleep(1)
        log.info(f"Started proxy")
        self.check_proxy()

    def kill_leftover_agents(self):
        log.debug("Killing leftover agents...")
        self.ssh_worker.exec_command(
            f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
        )
        log.debug("Killed leftover agents")

    def clear_dirs(self):
        log.debug("Deleting log/testcase directories...")
        self.ssh_worker.exec_command(
            "rm -rf /home/fluffi_linux_user/fluffi/persistent/x64/logs /home/fluffi_linux_user/fluffi/persistent/x64/testcaseFiles"
        )
        log.debug("Log/testcase directories deleted")

    ### Fluffi Web ###

    def new_fuzzjob(self, name_prefix, target_path, module, seeds, library_path=None):
        name = f"{name_prefix}{int(time.time())}"
        log.debug(f"Creating new fuzzjob named {name}...")
        data = [
            ("name", (None, name)),
            ("subtype", (None, "X64_Lin_DynRioSingle")),
            ("generatorTypes", (None, 100)),  # RadamsaMutator
            ("generatorTypes", (None, 0)),  # AFLMutator
            ("generatorTypes", (None, 0)),  # CaRRoTMutator
            ("generatorTypes", (None, 0)),  # HonggfuzzMutator
            ("generatorTypes", (None, 0)),  # OedipusMutator
            ("generatorTypes", (None, 0)),  # ExternalMutator
            ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
            ("location", (None, self.location)),
            ("targetCMDLine", (None, os.path.join(SUT_PATH, target_path))),
            ("option_module", (None, "hangeTimeout")),
            ("option_module_value", (None, 5000)),
            ("targetModulesOnCreate", module),
            ("targetFile", (None, "")),
            ("basicBlockFile", (None, "")),
        ]
        for seed in seeds:
            data.append(("filename", seed))
        if library_path is not None:
            data.append(("option_module", (None, "additionalEnvParam")))
            data.append(
                (
                    "option_module_value",
                    (None, f"LD_LIBRARY_PATH={os.path.join(SUT_PATH, library_path)}"),
                )
            )
        while True:
            r = self.s.post(f"{FLUFFI_URL}/projects/createProject", files=data)
            if "Success" not in r.text:
                log.error(f"Error creating new fuzzjob named {name}: {r.text}")
                continue
            break
        id = r.url.split("/view/")[1]
        log.debug(f"Fuzzjob named {name} created with ID {id}")
        return Fuzzjob(self, id, name)

    def set_lm(self, num):
        log.debug(f"Setting LM to {num}...")
        while True:
            r = self.s.post(
                f"{FLUFFI_URL}/systems/configureSystemInstances/{self.worker_name}",
                files={
                    "localManager_lm": (None, num),
                    "localManager_lm_arch": (None, ARCH),
                },
            )
            if "Success!" not in r.text:
                log.error(f"Error setting LM to {num}: {r.text}")
                continue
            break
        self.manage_agents()
        log.debug(f"LM set to {num}")

    ### Polemarch ###

    def manage_agents(self):
        log.debug("Starting manage agents task...")
        s = util.FaultTolerantSession(self)
        s.auth = ("admin", "admin")
        r = s.post(f"{PM_URL}/project/1/periodic_task/3/execute/")
        history_id = r.json()["history_id"]
        time.sleep(1)
        while True:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
            if r.json()["status"] == "OK":
                break
            time.sleep(util.REQ_SLEEP_TIME)
        log.debug("Manage agents success")

    ### DB ###

    def get_fuzzjobs(self):
        log.debug("Fetching fuzzjobs...")
        self.db.select_db(DB_NAME)
        fuzzjobs = []
        with self.db.cursor() as c:
            c.execute("SELECT ID, name from fuzzjob")
            for id, name in c.fetchall():
                log.debug(f"Found fuzzjob with ID {id} and name {name}")
                fuzzjobs.append(Fuzzjob(self, id, name))
        log.debug("Fuzzjobs fetched")
        return fuzzjobs
