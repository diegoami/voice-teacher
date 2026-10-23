# Rclone for local and Claude cloud sessions

Rclone is already installed on the original machine. A local remote named
`voiceteacherdrive` has been created for folder
`1vco_myHt1RjR7U0OhdSMMZYiy4upVpfj`, with no Google login completed yet.
The saved goal2/malpaco logins returned `unauthorized_client` during this setup;
do not copy either token to Claude until a login has been verified.

## Authorize locally

Use your own Google OAuth **Desktop app** client, as recommended by
[rclone's Drive setup](https://rclone.org/drive/#making-your-own-client-id).
In Google Cloud Console select/create your project, enable the Google Drive API,
configure Google Auth Platform branding/audience (add your Google account as a
test user if testing), then create a Desktop app OAuth client. Keep its ID and
secret private; enter them in your own terminal rather than chat.

Run `rclone config`, choose **Edit existing remote**, then `voiceteacherdrive`.
Set client_id and client_secret to your working Desktop client credentials.
Keep scope `drive` and root_folder_id `1vco_myHt1RjR7U0OhdSMMZYiy4upVpfj`;
leave service_account_file blank. Use advanced config if needed to confirm the
root folder. Complete browser authentication and choose **No** for Shared Drive
(the folder is in My Drive). Keep the remote.

`drive.file` cannot see the existing archives uploaded by a different app.
The root folder controls the working directory, not OAuth permission scope.
If Google rejects authorization, diagnose its exact error before replacing a
token. `unauthorized_client` alone does not establish which client setting is wrong.

Verify in your own terminal:

```bash
rclone lsf voiceteacherdrive: --max-depth 1
```

It should list the POC and runtime archives and their JSON manifests. Only then
export the working credentials for Claude:

```bash
python3 tools/cloud/export_rclone_env.py
```

This prints only the path of a new mode-0600 temporary .env file; it does not
print credentials. Open that file locally, paste its entries into Claude's
`voice-teacher` environment variables, then delete it. It contains
`VOICE_TEACHER_RCLONE_TOKEN`, `RCLONE_DRIVE_CLIENT_ID` and
`RCLONE_DRIVE_CLIENT_SECRET`. Do not source it as a shell script, commit it,
upload it to Drive or paste it into chat.

## Claude cloud

[Cloud setup](cloud.md) installs rclone automatically if missing, using a pinned
Linux binary with a verified upstream SHA-256. No sudo is needed. Include
GitHub and its release-asset hosts in the custom network allowlist (already
listed in tools/cloud/allowed-domains.txt), and keep
`VOICE_TEACHER_INSTALL_RCLONE=1` (the default). The setup adds the checkout-owned
`.cache/tools/bin` to PATH; source `.cache/cloud.env` when running manually.

Start a fresh Claude session after saving the three environment values. Verify:

```bash
source .cache/cloud.env
rclone version
python3 tools/artifacts.py pull poc2-fixtures-2026-10-23.tar.gz
```

The artifact helper constructs its own project-scoped remote from environment
values; it deliberately does not inherit a machine's rclone configuration.
It verifies the known archive's SHA-256 after download. Cloud access remains
unverified until this succeeds in an actual Claude session.
