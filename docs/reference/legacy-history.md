# Readable legacy history

History contains a separate **Legacy session archive**. It reads only original
inputs already retained by an approved historical import. The server never opens
source paths requested by a browser. Each opaque ID identifies one retained input
in one reviewed import snapshot. Different import snapshots remain distinct even
when they retain identical original bytes with different mappings.

Session records appear separately from supporting tracker and queue references.
A source whose original heading identifies a transcript is labelled **Transcript
(as labelled in the source)**; a summary/notes heading is labelled accordingly.
Other session records explicitly say that a transcript was not identified. These
labels describe the retained source; they do not establish completeness. Original
text is displayed as plain text, including its original formatting and accents.
The date, when available, comes from the original source label and is identified
as such. No conversation is generated to fill gaps.

The detail exposes the original relative source label and SHA-256, the immutable
import identity, retained proposed/unresolved/conflicting counts, and selected
legacy observation groups supported by the source. Each group retains original
and practice source identities and supporting record IDs. Unresolved context is
readable without becoming accepted practice, mastery or lesson completion.

The list/detail endpoints require the existing paired-owner authentication and
query only that owner's imports. Reads validate the archived report against its
retained bytes and approval, and use a read-only database connection. Missing or
corrupt databases are reported unavailable without creating replacement state.
Missing IDs and other owners' IDs return 404. The archive works when original
source files or checkouts are no longer available because it uses retained text.
No credentials, import approvals, absolute runtime paths or other learners' batches
are returned. Client errors have an independent retry and do not operate on active
recordings or accepted answers.

## Current readable scope

The owner's existing approved initial batch contains three original inputs:
**one transcript-labelled session record, one tracker and one repetition queue**.
Together they retain 335 extracted records: 75 supporting records across nine
selected legacy groups and 260 unresolved context records. Those original inputs
are readable in full, including unresolved context; this does not mean all
historical sessions were imported or all retained mappings were resolved.

A private local verification restored the already approved remote batch into a
fresh private verification ledger, read all three inputs through this projection,
and checked their complete text against the retained source SHA-256 values.
The remote batch files were unchanged and an unrelated synthetic owner saw no
records. No additional historical input was applied or pushed. No personal text,
source paths or private manifest enters the code repository or review packet.

Other historical transcript files remain outside this archive until an explicit
additional manifest is reviewed, applied and reconciled using the
[existing migration process](migration-apply.md). Neither enabling this view nor
creating its task authorizes another import. The deployed runtime must already
load its verified legacy ledger via the existing `legacy=` configuration; this
view does not silently attach another progress destination.

**Incomplete:** owner confirmation on the actual phone that expected records
are visible; additional reviewed historical imports; independent merge approval.
Browser emulation, local restoration and synthetic records do not satisfy the
phone check or imply a deployment has happened.
