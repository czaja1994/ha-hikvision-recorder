# Hikvision Recorder

[Polski](#polski) | [English](#english)

---

## Polski

Integracja Home Assistant do sterowania nagrywaniem i nadzoru kamer na rejestratorach Hikvision (NVR) przez ISAPI. Działa lokalnie, bez chmury i bez zewnętrznych zależności (`requirements: []`). Odpytuje NVR co 30 s.

Przetestowana na żywo na NVR-4CH-POE z firmware V4.30.216.

### Co robi

Wszystko trafia do jednego urządzenia "Network Video Recorder":

| Encja | Opis |
|---|---|
| Przełącznik **Recording** | Włącza/wyłącza nagrywanie wszystkich kamer. Jest włączony, gdy harmonogram którejkolwiek kamery jest włączony. Atrybut `cameras` pokazuje stan per kamera. |
| Czujnik binarny **`<Kamera>` online** | Łączność kamery z rejestratorem (`connectivity`). |
| Czujnik binarny **`<Kamera>` recording** | Czy kamera faktycznie nagrywa w tej chwili (`running`). |
| Przycisk **Restart NVR** | Restartuje rejestrator. |
| Czujnik **Last restart** | Czas ostatniego restartu (timestamp). |

Lista kamer pochodzi z konfiguracji kanałów, więc encje kamery powstają także wtedy, gdy kamera jest offline w chwili startu HA. Gdy cały NVR jest nieosiągalny albo się restartuje, encje przechodzą w `unavailable` (a nie w `off`), więc automatyzacje typu watchdog nie liczą tego jako awarii kamery.

### Jak działa włączanie i wyłączanie nagrywania

Przełącznik zmienia wyłącznie flagę harmonogramu per ścieżka (`CustomExtension/enableSchedule` w `PUT /ISAPI/ContentMgmt/record/tracks/<id>`). Treść harmonogramu nigdy nie jest zmieniana, a reszta XML-a jest odsyłana bajt w bajt. Jedyny inny zapis na NVR to `PUT /ISAPI/System/reboot` (przycisk Restart NVR). Jeśli zapis uda się tylko dla części kamer, integracja próbuje wszystkich, a potem zgłasza błąd z nazwami kamer, których nie udało się przełączyć.

### Uprawnienia konta NVR

Utwórz na rejestratorze osobnego użytkownika z uprawnieniami (Remote):

- Parameters Settings,
- Log Search / Interrogate Working Status,
- Shutdown / Reboot,
- Live View.

### Instalacja przez HACS (custom repository)

1. HACS, menu z trzema kropkami, **Custom repositories**.
2. Dodaj `https://github.com/czaja1994/ha-hikvision-recorder`, kategoria **Integration**.
3. Zainstaluj **Hikvision Recorder** i zrestartuj Home Assistant.
4. **Ustawienia, Urządzenia i usługi, Dodaj integrację, Hikvision Recorder**. Podaj adres NVR, użytkownika i hasło.

Wymaga Home Assistant 2026.11.0 lub nowszego (patrz `hacs.json`).

### Działa obok `hikvision_next`

Integracja nie dotyka ustawień `hikvision_next` (Notifications Host, Holiday Mode, harmonogram świąteczny) i może działać równolegle. Uwaga: od HA 2026.8 urządzenia nie są łączone między integracjami, więc przy zainstalowanym `hikvision_next` zobaczysz dwa urządzenia NVR, po jednym na integrację.

### Rozwój

```
uv venv -p 3.14
uv pip install -r requirements_test.txt
uv run pytest
```

Testy działają na HA 2026.10.4 (pytest-homeassistant-custom-component 0.13.375), bo żadne wydanie wtyczki nie przypina jeszcze 2026.11. Testy nie wymagają NVR ani pliku `.env`.

---

## English

A Home Assistant integration for controlling recording and watching cameras on Hikvision NVRs over ISAPI. It runs locally, with no cloud and no external dependencies (`requirements: []`). It polls the NVR every 30 s.

Tested live on an NVR-4CH-POE running firmware V4.30.216.

### What it does

Everything lives under one "Network Video Recorder" device:

| Entity | Description |
|---|---|
| **Recording** switch | Turns recording on/off for all cameras. It is on if any camera's schedule is enabled. The `cameras` attribute shows per-camera state. |
| **`<Camera>` online** binary sensor | Camera connectivity to the NVR (`connectivity`). |
| **`<Camera>` recording** binary sensor | Whether the camera is actually recording right now (`running`). |
| **Restart NVR** button | Reboots the recorder. |
| **Last restart** sensor | Timestamp of the last restart. |

The camera list comes from the channel configuration, so camera entities exist even when a camera is offline at HA startup. When the whole NVR is unreachable or rebooting, entities become `unavailable` (not `off`), so watchdog automations do not count it as a camera failure.

### How recording on/off works

The switch only changes the per-track schedule enable flag (`CustomExtension/enableSchedule` in `PUT /ISAPI/ContentMgmt/record/tracks/<id>`). The schedule itself is never changed, and the rest of the XML is sent back byte for byte. The only other write to the NVR is `PUT /ISAPI/System/reboot` (the Restart NVR button). If the write succeeds for only some cameras, the integration tries all of them and then raises an error naming the cameras that could not be switched.

### NVR account permissions

Create a dedicated user on the recorder with these (Remote) permissions:

- Parameters Settings,
- Log Search / Interrogate Working Status,
- Shutdown / Reboot,
- Live View.

### Installation via HACS (custom repository)

1. HACS, three-dot menu, **Custom repositories**.
2. Add `https://github.com/czaja1994/ha-hikvision-recorder` as category **Integration**.
3. Install **Hikvision Recorder** and restart Home Assistant.
4. **Settings, Devices & services, Add integration, Hikvision Recorder**. Enter the NVR address, username and password.

Requires Home Assistant 2026.11.0 or newer (see `hacs.json`).

### Works alongside `hikvision_next`

This integration does not touch `hikvision_next` settings (Notifications Host, Holiday Mode, holiday schedule) and can run in parallel. Note: since HA 2026.8 devices are not merged across integrations, so with `hikvision_next` installed you will see two NVR devices, one per integration.

### Development

```
uv venv -p 3.14
uv pip install -r requirements_test.txt
uv run pytest
```

Tests run on HA 2026.10.4 (pytest-homeassistant-custom-component 0.13.375) because no plugin release pins 2026.11 yet. Tests need neither an NVR nor a `.env` file.
