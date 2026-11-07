// ---------------------------------------------------------------------------
// PitBoss R3E - VR-Layer Pruefprogramm (PoC-Diagnose)
// ---------------------------------------------------------------------------
// Doppelklick-Anwendung: prueft ohne VR und ohne OpenXR-Runtime, ob der
// PitBoss-VR-Layer korrebiert registriert und ladbar ist. Es wird dieselbe
// Kette getestet, die der OpenXR-Loader durchlaeuft:
//   1. Registry-Eintraege (HKLM und HKCU, ApiLayers\Implicit)
//   2. Manifest-Datei lesbar? library_path/name daraus
//   3. DLL: Browser-Sperrvermerk (Zone.Identifier)? ladbar? Exports vorhanden?
// Das Laden der PitBoss-DLL schreibt dabei auch das bekannte Logbuch nach
// %TEMP%\PitBossVR_layer.log. Ergebnis: pitboss_vr_check.txt neben der EXE.
// ---------------------------------------------------------------------------

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>

static FILE* g_out = nullptr;

static void Say(const char* fmt, ...) {
    char buf[1024];
    va_list a;
    va_start(a, fmt);
    _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, a);
    va_end(a);
    printf("%s\r\n", buf);
    if (g_out) fprintf(g_out, "%s\r\n", buf);
}

static std::string ReadFileToString(const char* path) {
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                           OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return "";
    std::string s;
    char chunk[4096];
    DWORD n = 0;
    while (ReadFile(h, chunk, sizeof(chunk), &n, nullptr) && n)
        s.append(chunk, n);
    CloseHandle(h);
    return s;
}

// Naiver JSON-String-Wert (reicht fuer unser festes Manifest)
static std::string ExtractJsonString(const std::string& json, const char* key) {
    std::string pat = std::string("\"") + key + "\"";
    size_t k = json.find(pat);
    if (k == std::string::npos) return "";
    size_t c = json.find(':', k + pat.size());
    if (c == std::string::npos) return "";
    size_t q1 = json.find('"', c);
    if (q1 == std::string::npos) return "";
    size_t q2 = json.find('"', q1 + 1);
    if (q2 == std::string::npos) return "";
    return json.substr(q1 + 1, q2 - q1 - 1);
}

static bool MotWPresent(const char* path) {
    std::string zs = std::string(path) + ":Zone.Identifier";
    HANDLE h = CreateFileA(zs.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
                           OPEN_EXISTING, 0, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    CloseHandle(h);
    return true;
}

static void CheckLayerEntry(const char* hiveName, const char* manifestPath) {
    Say("");
    Say("[%s] Eintrag: %s", hiveName, manifestPath);

    std::string man = ReadFileToString(manifestPath);
    if (man.empty()) {
        Say("  -> FEHLER: Manifest-Datei nicht lesbar (Pfad falsch oder blockiert).");
        return;
    }
    std::string lib   = ExtractJsonString(man, "library_path");
    std::string lname = ExtractJsonString(man, "name");
    Say("  -> Manifest lesbar. Name: %s | library_path: %s",
        lname.c_str(), lib.c_str());
    if (lname.empty() || lib.empty()) {
        Say("  -> FEHLER: Manifest unvollstaendig (Name oder library_path fehlt).");
        return;
    }

    // Relativen library_path am Manifest-Ordner aufloesen
    std::string dir;
    {
        std::string n(manifestPath);
        size_t p = n.find_last_of("\\/");
        if (p != std::string::npos) dir = n.substr(0, p + 1);
    }
    std::string libPath = (lib.find(':') == std::string::npos) ? dir + lib : lib;

    if (MotWPresent(libPath.c_str()))
        Say("  -> ACHTUNG: DLL traegt noch den Browser-Sperrvermerk "
            "(Zone.Identifier). Freigeben: Unblock-File oder Eigenschaften -> Zulassen.");

    HMODULE h = LoadLibraryA(libPath.c_str());
    if (!h) {
        Say("  -> FEHLER: DLL nicht ladbar, Windows-Fehlercode %lu "
            "(blockiert, 32/64-Bit-Mix oder defekt).", GetLastError());
        return;
    }
    Say("  -> DLL erfolgreich geladen.");
    bool gpa1 = GetProcAddress(h, "LayerGetInstanceProcAddr") != nullptr;
    bool gpa2 = GetProcAddress(h, "xrCreateApiLayerInstance") != nullptr;
    if (gpa1 && gpa2)
        Say("  -> Exports LayerGetInstanceProcAddr / xrCreateApiLayerInstance vorhanden.");
    else
        Say("  -> FEHLER: erwartete Exports fehlen (gpa1=%d, gpa2=%d).",
            gpa1 ? 1 : 0, gpa2 ? 1 : 0);
    FreeLibrary(h);
    Say("  => Registrierung und DLL sind in Ordnung; der Layer muesste "
        "vom Spiel geladen werden.");
}

static void CheckHive(HKEY root, const char* hiveName) {
    HKEY k = nullptr;
    LONG ok = RegOpenKeyExA(root,
        "SOFTWARE\\Khronos\\OpenXR\\1\\ApiLayers\\Implicit",
        0, KEY_READ, &k);
    if (ok != ERROR_SUCCESS) {
        Say("");
        Say("[%s] Kein Schluessel ApiLayers\\Implicit vorhanden "
            "(keine impliziten Layer registriert).", hiveName);
        return;
    }
    bool any = false;
    for (DWORD idx = 0;; ++idx) {
        char name[1024];
        DWORD nameLen = sizeof(name);
        if (RegEnumValueA(k, idx, name, &nameLen, nullptr, nullptr,
                          nullptr, nullptr) != ERROR_SUCCESS) break;
        DWORD v = 0, vlen = sizeof(v), type = 0;
        if (RegQueryValueExA(k, name, nullptr, &type,
                             (LPBYTE)&v, &vlen) != ERROR_SUCCESS
            || type != REG_DWORD) continue;
        any = true;
        if (v != 0) {
            Say("");
            Say("[%s] Eintrag: %s = %lu", hiveName, name, v);
            Say("  -> Wert ungleich 0: Eintrag ist DEAKTIVIERT "
                "(der Wert muss 0 sein).");
            continue;
        }
        CheckLayerEntry(hiveName, name);
    }
    if (!any) {
        Say("");
        Say("[%s] Schluessel vorhanden, aber leer.", hiveName);
    }
    RegCloseKey(k);
}

int main() {
    fopen_s(&g_out, "pitboss_vr_check.txt", "w");
    Say("PitBoss R3E - VR-Layer Pruefung (PoC)");
    Say("====================================");
    char proc[MAX_PATH] = {0};
    GetModuleFileNameA(nullptr, proc, MAX_PATH);
    Say("Pruefprogramm: %s", proc);
    Say("(Dieses Programm nutzt die gleiche Kette wie der OpenXR-Loader,");
    Say(" benoetigt aber weder VR-Headset noch eine OpenXR-Runtime.)");

    CheckHive(HKEY_LOCAL_MACHINE, "HKLM alle Nutzer");
    CheckHive(HKEY_CURRENT_USER, "HKCU aktueller Nutzer");

    Say("");
    Say("Hinweis: Wurde die PitBoss-DLL oben erfolgreich geladen, sollte jetzt");
    Say("zusaetzlich die Datei PitBossVR_layer.log in %%TEMP%% existieren");
    Say("(Windows-Taste + R, %%temp%%, Enter).");
    if (g_out) fclose(g_out);
    Say("");
    Say("Ergebnis steht in pitboss_vr_check.txt (im Ordner dieses Programms).");
    printf("Enter zum Schliessen... ");
    getchar();
    return 0;
}
