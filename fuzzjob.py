import time

import fluffi
import util

# Constants
DB_FUZZJOB_FMT = "fluffi_{}"


class Fuzzjob:
    def __init__(self, f, id, name):
        self.f = f
        self.id = id
        self.name = name
        self.db = DB_FUZZJOB_FMT.format(name)

    ### Fluffi Web ###

    def archive(self):
        self.f.debug("Archiving fuzzjob...")
        self.f.s.post(f"{fluffi.FLUFFI_URL}/projects/archive/{self.id}")
        while True:
            r = self.f.s.get(f"{fluffi.FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(util.REQ_SLEEP_TIME)
        self.f.debug("Fuzzjob archived")

    def set_gre(self, gen, run, eva):
        self.f.debug(f"Setting GRE to {gen}, {run}, {eva} for {self.name}...")
        while True:
            r = self.f.s.post(
                f"{fluffi.FLUFFI_URL}/systems/configureFuzzjobInstances/{self.name}",
                files={
                    f"{self.f.worker_name}_tg": (None, gen),
                    f"{self.f.worker_name}_tg_arch": (None, fluffi.ARCH),
                    f"{self.f.worker_name}_tr": (None, run),
                    f"{self.f.worker_name}_tr_arch": (None, fluffi.ARCH),
                    f"{self.f.worker_name}_te": (None, eva),
                    f"{self.f.worker_name}_te_arch": (None, fluffi.ARCH),
                },
            )
            if "Success!" not in r.text:
                self.f.error(
                    f"Error setting GRE to {gen}, {run}, {eva} for {self.name}: {r.text}"
                )
                continue
            break
        self.f.manage_agents()
        self.f.debug(f"GRE set to {gen}, {run}, {eva} for {self.name}")
