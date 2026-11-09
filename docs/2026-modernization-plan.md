# Storybutton integration — 2026 modernization plan

Status: **proposed** · Scope agreed: **Tier 1 + Tier 2** · Author: @dacort (+ Claude)

## Goal / problem

When a Storybutton's IP changes (e.g. it moved rooms / got a new DHCP lease), the
integration loses it — there's no way to re-point it short of remove-and-re-add or hand-editing
`.storage/core.config_entries`. Root cause: the config entry has **no `unique_id` and no
discovery**, so Home Assistant can't recognize the device across an IP change.

Fix: make the device self-identifying (stable `unique_id`) and self-healing (SSDP discovery
that auto-updates the host), plus a manual reconfigure fallback. Then bring the integration up
to current HA patterns while we're in here.

## Device facts (from live `device.xml`, 192.168.7.48)

- **UDN** `uuid:50b25025-9478-8092-a31c-00112238d9ea` → stable `unique_id`
- **manufacturer** `Storybutton` → specific SSDP matcher
- **deviceType** `urn:schemas-upnp-org:device:MediaRenderer:1` (UPnP MediaRenderer → advertises via SSDP)
- model `SB-100` / modelNumber `PR-100v2` / firmware `Internet Radio 20250103.1801` / serial present
- UDN tail embeds MAC `00:11:22:38:d9:ea` (DHCP-by-MAC available as a backup path)

## ⚠️ Field finding (2026-06-27): the device does NOT broadcast

Verified against the live device at `192.168.7.48` (same `/24` as the test host):
- Serves `device.xml` over HTTP ✅ (this is how we get the UDN), and *claims* DLNA `DMR-1.50`…
- …but answered **0** SSDP M-SEARCHes (`ssdp:all` got 40 other responders on the subnet), sent
  **no** `NOTIFY` in a 5-min passive listen, and exposes **no** mDNS/zeroconf service.

**Consequence:** the SSDP self-heal can never fire. Pivoted self-heal to **DHCP-by-MAC** (the
device *does* take DHCP leases — that's the root cause), and **removed the SSDP step + matcher**.
The stable-identity + **reconfigure** spine still fully solves the original "device moved, can't
re-point it" problem; DHCP makes the recovery automatic when HA can observe the lease.

## Design decisions

1. **`unique_id` = UPnP UDN.** Available in every path: user setup (fetch `device.xml`),
   DHCP (fetch `device.xml` at the leased IP). (SSDP path removed — device doesn't broadcast.)
2. **Entity `unique_id` re-based on the UDN, via an in-place registry migration.**
   `async_migrate_entry` rewrites each entity's registry `unique_id` from the old `entry_id`
   to the UDN **while preserving the `entity_id`**, so `media_player.amelias_storybutton` /
   `..._cooper_s_storybutton` keep working and Bubble Dash is untouched. Fallback: if the device
   is unreachable when migration runs (Amelia, until her one reconfigure), defer — the entity
   keeps its old `entry_id` unique_id and still works; migrate opportunistically once the UDN is
   known. (Owner approved orphan-and-recreate if ever needed, but we aim for zero breakage.)
   ⚠️ Cross-repo: this can change storybutton `entity_id`s if the in-place migration can't run —
   see the heads-up note in the **homelab** repo (`home_assistant/README.md`).
3. **DHCP-by-MAC is the primary IP-update mechanism** (was SSDP — see field finding above).
   ⚠️ **The UDN's embedded MAC is a placeholder** (`00:11:22:38:d9:ea`) — the real network MAC is
   Espressif: Amelia `34:85:18:ae:37:1c`, Cooper `34:85:18:ad:c6:b0`. So `manifest.json` matches
   `macaddress: "348518*"` (shared OUI), and the real MAC is taken from the DHCP payload (not the
   UDN), stored on the entry (`CONF_MAC`), and used for the device-registry `connections`.
   `async_step_dhcp` fetches `device.xml` at the leased IP, confirms by UDN, updates host+MAC.
   ⚠️ `348518*` is the Espressif OUI — it matches *many* ESP devices, so unrelated hits will fire a
   flow that aborts `cannot_connect`; could narrow by DHCP hostname later. Requires HA to actually
   observe DHCP. Manual **reconfigure** remains the always-works fallback.
4. **Backfill for existing entries.** Amelia's & Cooper's entries currently have
   `unique_id = None`. On setup, if the device is reachable at the stored host, backfill
   `entry.unique_id` from `device.xml` so DHCP can match it thereafter. Amelia's stored IP is
   stale (device moved), so the device isn't reachable there — recovery is **one** manual
   reconfigure to `192.168.7.48`, which both fixes the host and backfills the UDN; future moves
   then self-heal via DHCP.

## In scope (Tier 1 + 2)

### Tier 1 — solve the moved-device problem
- [x] `manifest.json`: ~~`"ssdp"`~~ → **`"dhcp": [{ "macaddress": "001122*" }]`**; bump version (→ `0.2.0`).
- [x] Pure helper `DeviceDescription.from_xml(text)` in `storybutton.py` (udn, friendly_name,
      manufacturer, model, sw_version, serial) — no HA deps, unit-tested against the **real**
      `device.xml`. `sw_version` is read from `<modelDescription>` (confirmed:
      `Internet Radio 20250103.1801`). MAC is **not** parsed from the UDN (it's a placeholder there) —
      the real network MAC comes from DHCP discovery and is stored on the entry.
- [x] Async `device.xml` fetch (`async_fetch_device_description`, HA aiohttp session) used by the flow.
- [x] `config_flow.py`:
  - [x] `async_step_user`: fetch device.xml → `async_set_unique_id(udn)` →
        `_abort_if_unique_id_configured()` → create entry. Error `cannot_connect` on failure.
  - [x] `async_step_dhcp` (replaces SSDP): fetch device.xml at `discovery_info.ip` → set unique_id by
        UDN → `_abort_if_unique_id_configured(updates={CONF_HOST: ip, CONF_MAC: mac})` (self-heals
        existing entries) → `discovery_confirm` form for new devices. Captures the real network MAC
        (`format_mac(discovery_info.macaddress)`). Aborts `cannot_connect` if not a reachable Storybutton.
  - [x] `async_step_reconfigure`: prefilled host form; validate via device.xml; backfill UDN +
        guard against re-pointing at a different device (`_abort_if_unique_id_mismatch`);
        `async_update_reload_and_abort(unique_id=, data_updates={CONF_HOST})` (auto-reloads).
        (Flips `supports_reconfigure` → true; answers the original "edit the IP" ask.)

### Tier 2 — HA 2026 hygiene
- [x] `media_player.py`: add `DeviceInfo` (identifiers={(DOMAIN, udn)}, manufacturer/model/sw_version
      from device.xml, connections={(CONNECTION_NETWORK_MAC, mac)} from the **DHCP-captured** MAC on
      the entry, omitted until known) → real device page, fixes `device_id: None`.
- [x] `strings.json` + `translations/en.json`: labels/descriptions for the `user` /
      `discovery_confirm` / `reconfigure` steps and the `cannot_connect` / `wrong_device` /
      `already_configured` / `reconfigure_successful` messages. *(Pulled forward from Tier 3.)*
- [x] `__init__.py`: fix anti-pattern `hass.async_create_task(async_forward_entry_setups(...))`
      → `await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)`; adopt typed
      `StorybuttonConfigEntry` / `entry.runtime_data`. Reconfigure reload is handled by
      `async_update_reload_and_abort`; DHCP host updates reload via `_abort_if_unique_id_configured`.
- [x] `media_player.py`: replace deprecated `STATE_*` strings with `MediaPlayerState` enum.
- [x] `async_migrate_entry` (`1.0 → 1.1`): backfill `entry.unique_id` from `device.xml` (design #4)
      **and** rewrite entity registry unique_id `entry_id` → UDN in place, preserving `entity_id`
      (design #2), factored into idempotent `_async_backfill_identity`. Both deferred gracefully if
      device unreachable, and retried opportunistically on every `async_setup_entry` (so Amelia's
      one reconfigure, which sets the UDN, completes the entity migration on the following reload).

## Deferred (Tier 3, not now)
`requests` → async `aiohttp` · drop legacy YAML `async_setup_platform`.
**Pulled forward (done):** DHCP-by-MAC (now primary, not a backup) · `strings.json` + translations ·
config/discovery-flow + migration tests (`pytest-homeassistant-custom-component` is now installed).
**Still want:** confirm HA's `dhcp` integration actually sees leases on this network (else self-heal
silently won't fire). OUI is confirmed: both units are Espressif `34:85:18` (Amelia `…:ae:37:1c`,
Cooper `…:ad:c6:b0`); the broad `348518*` match could later be narrowed by DHCP hostname.

## Environment caveats
- **Done: dev HA pin bumped `2024.12.5` → `2026.6.4`** (matches the running line). The whole
  2026.3+ line requires **Python 3.14.2+**, so the dev venv was recreated on Python 3.14
  (`.python-version` → `3.14`, `requires-python` → `>=3.14.2`). Used the current stable APIs:
  `DhcpServiceInfo` from `homeassistant.helpers.service_info.dhcp`, and the
  `_get_reconfigure_entry` / `async_update_reload_and_abort` reconfigure helpers.
- **3.14 build fallout** (pinned in `[tool.uv]` of `pyproject.toml`): legacy sdists in HA's
  transitive tree don't build on 3.14 — `build-constraint-dependencies = ["setuptools<81"]`
  (old pyobjc `setup.py` imports `pkg_resources`), and `override-dependencies` force modern
  `lxml>=6`, `pyobjc-*>=12`, and `mashumaro>=3.22` (3.15 mis-compiles `Union[str, list[str]]`
  on 3.14, breaking the `webrtc_models` import HA pulls in).
- `defusedxml` added to dev deps and used for `device.xml` parsing (it's a HA core dep at runtime,
  so not added to `manifest.json` requirements). `pytest-homeassistant-custom-component==0.13.340`
  (pins HA 2026.6.4) **now installed** for flow/migration tests; needed `asyncio_mode = "auto"`
  and an `httpcore>=1.0.9` override (1.0.7 trips on `typing.Union` under 3.14).

## Verification
- `python -m pytest -q` green — **28 tests pass** (15 device baseline + 3 `from_xml` +
  8 config/DHCP/reconfigure flow + 2 migration).
- Lint clean (`ruff check`), formatted (`ruff format`).
- Manual still TODO: reconfigure Amelia's to `192.168.7.48` → entity recovers, keeps its entity_id +
  device page populated; then move device → confirm HA's DHCP discovery auto-updates the host.

## Resolved
1. ✅ Bump dev HA pin toward 2026 before coding.
2. ✅ Re-base entity unique_id on UDN via in-place migration (decision #2); owner OK with
   recreate fallback if the in-place path can't run.
