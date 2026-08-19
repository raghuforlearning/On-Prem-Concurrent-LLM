# P1-21 Windows Document Worker Feasibility

Date: 19-Aug-2026

Status: **FOUNDATION IMPLEMENTED / CANDIDATE-VM ACCEPTANCE NOT PASSED**

## Boundary

The worker is downstream of the frozen NationLabs Proposal Builder. It may:

- accept only a hash-verified, security-cleared Builder-produced DOCX from an
  allow-listed local artifact root;
- open it in an isolated Microsoft Word process;
- update Word fields, repaginate, save the rendered DOCX and export PDF;
- return hashes and render metadata;
- retry once, terminate the exact process tree and quarantine failures.

It must not create proposal content, apply the golden template, place BOQ or
commercial tables, calculate prices, or repair a Builder output. Those remain
Proposal Builder responsibilities. A render worker therefore cannot make the
P1-20 nine-page non-conforming TP into the 26-page golden TP by itself.

## Implemented Orchestrator components

- `build/p1-25/app/document_worker.py`: immutable request contract, controlled
  roots, source and clearance hash verification, macro rejection, deterministic
  request hash, process-wide serialized execution, bounded retry, output hash
  verification and quarantine evidence.
- `build/p1-25/app/windows-document-worker/Invoke-DocumentRender.ps1`: isolated
  Word COM renderer with macros disabled, external-link updates disabled, exact
  Word PID evidence, DOCX save, PDF export and COM cleanup.
- `build/p1-25/app/tests/test_p121_document_worker.py`: offline contract,
  idempotency, serialization, artifact verification and quarantine tests.

## Local feasibility evidence

- Microsoft Word COM 16.0 is installed and can be created invisibly.
- Golden TP SHA-256:
  `01adc6e02ac93e93c45fd02ad94808142bd5cc7a67be4abf5ad05589ac5bbe0a`.
- Frozen Builder TP input SHA-256:
  `13d4af9773b3277543f51b234d806d7b98ffd8f375916844a40d9019e706494c`.
- Unit/regression suite: 27 passed.
- Real Builder TP job `p121-live-tp-isolated` did not complete Word rendering
  within 90 seconds on either attempt. The supervisor terminated the exact
  Word process, quarantined the job and left no `WINWORD.EXE` process.
- Milestone logging isolated the first blocking call to `SaveAs2`. The worker
  was changed to copy the immutable source, open only that isolated working
  copy and call `Save()`; DOCX save then completed normally.
- Real Builder CP job `p121-live-cp-180` opened, updated fields, repaginated and
  saved the working-copy DOCX in about ten seconds, but Word's PDF export did
  not return within 180 seconds. The worker killed the exact Word PID,
  quarantined the job and again left no ghost Word process.
- This is a valid failure result, not production acceptance. It confirms the
  unattended Office risk on the real document and proves the current output
  must remain quarantined.

## WT-1 through WT-8 state

| Gate | Current state | Required completion evidence |
|---|---|---|
| WT-1 | Not run | 50/50 Word jobs under the candidate service account, no interactive session, no ghost Word process |
| WT-2 | Not run | Excel range to Word EMF paste under the candidate service account, visual parity with approved reference |
| WT-3 | Failed locally for real Builder CP/TP | Word PDF export did not complete; candidate VM must prove page-count parity and raster comparison within the approved threshold |
| WT-4 | Partial | Exact PID termination, retry and quarantine work; candidate VM must detect a modal/hang in 60 seconds or less and recover cleanly |
| WT-5 | Not run | LibreOffice-versus-Word render comparison with an agreed threshold |
| WT-6 | Unit passed | Two concurrent jobs serialize to maximum Office concurrency one; repeat on candidate VM |
| WT-7 | Not run | Windows service auto-start and PostgreSQL-backed queue resume after reboot with zero lost jobs |
| WT-8 | Contract passed | Worker refuses non-cleared, hash-mismatched, macro-bearing or out-of-root sources; repeat with production malware-clearance evidence |

## Candidate VM acceptance sequence

1. IT approves a dedicated Windows Server 2022 VM, 4 vCPU, 16 GB RAM, 250 GB
   disk and licensed Office. Do not co-host this in the frozen AI Inference or
   Proposal Builder VMs.
2. Create a dedicated low-privilege service account and deny interactive logon
   except an audited break-glass procedure.
3. Copy the Orchestrator worker package and unchanged Proposal Builder runtime
   through controlled media; register hashes before service start.
4. Configure default-deny firewall rules, no internet gateway, macros disabled,
   and only Orchestrator-to-worker traffic.
5. Execute WT-1 through WT-8 and retain JSON results, process evidence, rendered
   DOCX/PDF hashes and visual-diff images.
6. P1-21 can be marked passed only when WT-1, WT-2, WT-4 and WT-7 pass on that
   VM and the resulting TP independently passes the P1-20 gate.
