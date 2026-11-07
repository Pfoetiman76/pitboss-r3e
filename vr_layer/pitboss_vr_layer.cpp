// ---------------------------------------------------------------------------
// PitBoss R3E - OpenXR API Layer "VR Overlay" (Proof of Concept, 0.4.0.0)
// ---------------------------------------------------------------------------
// Blaendet eine virtuelle Tafel (Quad-Layer) in die OpenXR-Szene des Spiels
// ein. Funktioniert mit jeder OpenXR-Runtime, also ausdruecklich auch mit
// Virtual Desktop / VDXR (kein SteamVR noetig) - der Layer laeuft im
// Spielprozess.
//
// Architektur:
//   PitBoss (Python) rendert die Overlay-Inhalte als BGRA-Bild in den
//   Shared-Memory-Puffer "Local\\PitBossR3E_VR" (Header: magic, version,
//   width, height, frame). Der Layer liest diesen Puffer und legt ihn als
//   Quad-Layer ueber die Szene. Fehlt der Puffer (PitBoss laeuft nicht),
//   zeigt der Layer ein ruhiges Testmuster - so ist der PoC ohne PitBoss
//   pruefbar ("Testtafel").
//
// Aktivierung: impliziter Layer (Registry, siehe vr_layer/README.md).
//   Explizite Layer werden nur geladen, wenn die Anwendung sie selbst
//   anfordert - RaceRoom tut das nicht. Implizite Layer laden dagegen
//   systemweit, deshalb aktiviert sich dieser Layer NUR im RaceRoom-
//   Prozess (Zielprozess-Filter unten) und verhaelt sich in allen anderen
//   OpenXR-Anwendungen vollstaendig passiv.
//
// Diagnose: jede Log-Meldung wird nach %TEMP%\\PitBossVR_layer.log
//   geschrieben (PoC-Hilfsmittel; wird mit der Integration entfernt).
//
// Verhandlung: Der aktuelle OpenXR-Loader verlangt zunaechst
//   xrNegotiateLoaderApiLayerInterface, uebergibt danach die klassische
//   xrCreateApiLayerInstance-Kette mit nextInfo. Das Manifest MUSS fuer
//   implizite Layer "disable_environment" enthalten, sonst verwirft der
//   Loader das Manifest stillschweigend (7.11.2026 gelernt).
//
// PoC-Einschraenkungen (dokumentiert, Ausbau in Folgeversionen):
//   - Eine Instanz; pro Session ein Zustand (erste Session aktiv).
//   - Textur-Updates ueber den Immediate Context des Spiels (D3D11).
//   - Feste Pose im LOCAL-Raum (oben, etwas vor dem Startpunkt).
//
// Build: siehe vr_layer/CMakeLists.txt (Windows, D3D11, statische CRT,
// vendored Header, kein Netzwerk-Zugriff noetig).
// ---------------------------------------------------------------------------

#define XR_USE_PLATFORM_WIN32
#define XR_USE_GRAPHICS_API_D3D11

#include <windows.h>
#include <d3d11.h>

#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <openxr/openxr_loader_negotiation.h>

#include <cstdarg>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <map>
#include <mutex>
#include <vector>

// Export fuer den OpenXR-Loader (GetProcAddress ueber die Manifest-Namen)
#ifdef _WIN32
  #define PVR_EXPORT __declspec(dllexport)
#else
  #define PVR_EXPORT
#endif

// ---------------------------------------------------------------------------
// Logging: DebugView (nur mit PVR_DEBUG) UND immer %TEMP%\\PitBossVR_layer.log
// ---------------------------------------------------------------------------

static void Log(const char* fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, args);
    va_end(args);
#ifdef PVR_DEBUG
    OutputDebugStringA("[PitBossVR] ");
    OutputDebugStringA(buf);
    OutputDebugStringA("\\n");
#endif
    char path[MAX_PATH];
    if (GetTempPathA(MAX_PATH, path) == 0) return;
    strcat_s(path, MAX_PATH, "PitBossVR_layer.log");
    HANDLE h = CreateFileA(path, FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    char line[620];
    _snprintf_s(line, sizeof(line), _TRUNCATE, "[%lu] %s\\r\\n",
                GetTickCount(), buf);
    DWORD written = 0;
    WriteFile(h, line, (DWORD)strlen(line), &written, nullptr);
    CloseHandle(h);
}

// ---------------------------------------------------------------------------
// Shared-Memory-Protokoll (identisch zur Python-Seite, siehe vr_layer/README)
// ---------------------------------------------------------------------------

struct SharedHeader {
    uint32_t magic;     // 'P','B','V','R' little-endian
    uint32_t version;   // 2 = Monitor-Spiegel (Leinwand + Pose); 1 = alte Einzeltafel
    uint32_t width;     // Leinwandbreite (z. B. 1920)
    uint32_t height;    // Leinwandhoehe (z. B. 1080)
    uint32_t frame;     // laufende Nummer, PitBoss inkrementiert pro Bild
    float    quadW;     // Tafelbreite in Metern (nur v2)
    float    quadH;     // Tafelhoehe in Metern (nur v2)
    float    posX;      // Position im LOCAL-Raum (nur v2)
    float    posY;
    float    posZ;
};
static const uint32_t kMagic     = 0x52564250;  // "PBVR" little-endian
static const uint32_t kVersionV1 = 1;
static const uint32_t kVersionV2 = 2;
static const uint32_t kTexWidth  = 512;   // Standard-Leinwand (v1 / Testmuster)
static const uint32_t kTexHeight = 256;
static const uint32_t kMaxCanvas = 4096;  // Obergrenze gegen defekte Header

// ---------------------------------------------------------------------------
// Globaler Layer-Zustand
// ---------------------------------------------------------------------------

static XrInstance                 g_instance = XR_NULL_HANDLE;
static PFN_xrGetInstanceProcAddr  g_nextGPA = nullptr;
static PFN_xrEndFrame             g_nextEndFrame = nullptr;

// Ueber g_nextGPA aufgeloeste Runtime-Funktionen
static PFN_xrEnumerateSwapchainFormats g_xrEnumerateSwapchainFormats;
static PFN_xrCreateSwapchain           g_xrCreateSwapchain;
static PFN_xrDestroySwapchain         g_xrDestroySwapchain;
static PFN_xrEnumerateSwapchainImages  g_xrEnumerateSwapchainImages;
static PFN_xrAcquireSwapchainImage     g_xrAcquireSwapchainImage;
static PFN_xrWaitSwapchainImage        g_xrWaitSwapchainImage;
static PFN_xrReleaseSwapchainImage     g_xrReleaseSwapchainImage;
static PFN_xrCreateReferenceSpace      g_xrCreateReferenceSpace;

// ---------------------------------------------------------------------------
// Zielprozess-Filter: Implizite Layer laden systemweit. Der Layer darf nur
// im RaceRoom-Prozess aktiv werden (RRRE.exe / RaceRoom*.exe); in jedem
// anderen OpenXR-Prozess bleibt er vollstaendig passiv (kein Hook, keine
// zusaetzliche Erweiterung, alles wird durchgereicht).
// ---------------------------------------------------------------------------

static bool g_targetProcess = false;

static bool IsRaceRoomProcess() {
    char path[MAX_PATH] = {0};
    if (GetModuleFileNameA(nullptr, path, MAX_PATH) == 0) return false;
    for (char* p = path; *p; ++p)
        *p = static_cast<char>(tolower(static_cast<unsigned char>(*p)));
    return strstr(path, "rrre") != nullptr
        || strstr(path, "raceroom") != nullptr;
}

// ---------------------------------------------------------------------------
// Per-Session Overlay-Zustand
// ---------------------------------------------------------------------------

struct OverlayState {
    bool        initialized = false;   // Init versucht (egal ob erfolgreich)
    bool        ok = false;            // Overlay einsatzbereit
    XrSwapchain swapchain = XR_NULL_HANDLE;
    XrSpace     space = XR_NULL_HANDLE;
    ID3D11Device*        device = nullptr;   // keine Referenz addiert
    ID3D11DeviceContext* context = nullptr;  // Immediate Context (keine Ref)
    std::vector<XrSwapchainImageD3D11KHR> images;
    XrCompositionLayerQuad quad{};
    std::vector<uint8_t> pixels;      // CPU-Bildpuffer (BGRA)
    uint32_t    texW = 0;             // aktuelle Leinwandgroesse
    uint32_t    texH = 0;
    int64_t     format = 0;           // gewaehltes Swapchain-Format
    uint32_t    lastFrame = 0xFFFFFFFFu;  // frame-Stand des letzten PitBoss-Bildes
    HANDLE      shm = nullptr;        // Shared Memory mit PitBoss
    SharedHeader* shmHeader = nullptr;
    uint8_t*    shmPixels = nullptr;
    uint64_t    tick = 0;
};

static std::mutex g_stateMutex;
static std::map<XrSession, OverlayState> g_sessions;

// ---------------------------------------------------------------------------
// Shared Memory mit PitBoss
// ---------------------------------------------------------------------------

static void CloseShm(OverlayState* st) {
    st->shmPixels = nullptr;
    st->shmHeader = nullptr;
    if (st->shm) { CloseHandle(st->shm); st->shm = nullptr; }
}

static void TryOpenShm(OverlayState* st) {
    if (st->shm) return;  // bereits offen
    HANDLE h = OpenFileMappingA(FILE_MAP_READ, FALSE, "Local\\PitBossR3E_VR");
    if (!h) return;
    void* p = MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0);
    if (!p) { CloseHandle(h); return; }
    st->shm = h;
    st->shmHeader = reinterpret_cast<SharedHeader*>(p);
    st->shmPixels = reinterpret_cast<uint8_t*>(p) + sizeof(SharedHeader);
}

static bool ShmValid(const OverlayState* st) {
    return st->shmHeader
        && st->shmHeader->magic == kMagic
        && (st->shmHeader->version == kVersionV1
            || st->shmHeader->version == kVersionV2)
        && st->shmHeader->width > 0 && st->shmHeader->width <= kMaxCanvas
        && st->shmHeader->height > 0 && st->shmHeader->height <= kMaxCanvas;
}

// Leinwandgroesse: mit gueltigem PitBoss-Anschluss dessen Masse, sonst
// der Standard 512x256 (altes Einzeltafel-Format / Testmuster).
static void ShmCanvasSize(const OverlayState* st, uint32_t& w, uint32_t& h) {
    w = kTexWidth;
    h = kTexHeight;
    if (ShmValid(st)) {
        w = st->shmHeader->width;
        h = st->shmHeader->height;
    }
}

// Tafel-Pose (v2): Groesse/Position aus PitBoss, sonst Standard.
static void ApplyShmPose(OverlayState* st) {
    if (ShmValid(st) && st->shmHeader->version == kVersionV2
        && st->shmHeader->quadW > 0.05f && st->shmHeader->quadW < 20.0f
        && st->shmHeader->quadH > 0.05f && st->shmHeader->quadH < 20.0f) {
        st->quad.size = {st->shmHeader->quadW, st->shmHeader->quadH};
        st->quad.pose.position = {st->shmHeader->posX,
                                  st->shmHeader->posY,
                                  st->shmHeader->posZ};
    } else {
        st->quad.pose.orientation = {0, 0, 0, 1};
        st->quad.pose.position = {0.f, 0.25f, -1.0f};
        st->quad.size = {0.5f, 0.25f};
    }
}

// ---------------------------------------------------------------------------
// Bildinhalt: PitBoss-Frame oder Testmuster
// ---------------------------------------------------------------------------

static void FillPixels(OverlayState* st) {
    // PitBoss-Bild uebernehmen, wenn vorhanden (Monitor-Spiegel)
    if (ShmValid(st)) {
        memcpy(st->pixels.data(), st->shmPixels,
               static_cast<size_t>(st->texW) * st->texH * 4);
        return;
    }
    // Testmuster (ohne PitBoss): Verlauf + Rahmen + wandernder Balken
    const uint32_t w = st->texW ? st->texW : kTexWidth;
    const uint32_t h = st->texH ? st->texH : kTexHeight;
    uint8_t* dst = st->pixels.data();
    const size_t rowBytes = w * 4;
    for (uint32_t y = 0; y < h; ++y) {
        uint8_t* row = dst + y * rowBytes;
        uint8_t v = static_cast<uint8_t>(40 + (y * 120) / h);
        for (uint32_t x = 0; x < w; ++x) {
            uint8_t* px = row + x * 4;
            px[0] = v;            // B
            px[1] = 0x30;         // G
            px[2] = 0x30;         // R
            px[3] = 0xFF;         // A
        }
    }
    for (uint32_t x = 0; x < w; ++x) {
        for (uint32_t e = 0; e < 3; ++e) {
            uint8_t* t = dst + e * rowBytes + x * 4;
            t[0] = t[1] = t[2] = 0xD0;
            uint8_t* b = dst + (h - 1 - e) * rowBytes + x * 4;
            b[0] = b[1] = b[2] = 0xD0;
        }
    }
    for (uint32_t y = 0; y < h; ++y) {
        for (uint32_t e = 0; e < 3; ++e) {
            uint8_t* l = dst + y * rowBytes + e * 4;
            l[0] = l[1] = l[2] = 0xD0;
            uint8_t* r = dst + y * rowBytes + (w - 1 - e) * 4;
            r[0] = r[1] = r[2] = 0xD0;
        }
    }
    // "Lebenszeichen": wandernder Block
    st->tick++;
    uint32_t bar = static_cast<uint32_t>((st->tick * 6) % (w > 96 ? w - 96 : 1));
    for (uint32_t y = (h > 64 ? h - 48 : 0); y < (h > 16 ? h - 16 : h); ++y) {
        for (uint32_t x = bar; x < bar + 96 && x < w; ++x) {
            uint8_t* px = dst + y * rowBytes + x * 4;
            px[0] = 0x60; px[1] = 0xC0; px[2] = 0x30; px[3] = 0xFF;  // gruen
        }
    }
}

// ---------------------------------------------------------------------------
// Overlay-Initialisierung pro Session
// ---------------------------------------------------------------------------

// Leinwand (Swapchain + Images + Geraet) in der Groesse cw x ch anlegen.
// Wird beim ersten Init und bei Groessenaenderungen aus PitBoss benutzt.
static bool CreateCanvasImpl(XrSession session, OverlayState* st,
                             uint32_t cw, uint32_t ch) {
    XrSwapchainCreateInfo sci{XR_TYPE_SWAPCHAIN_CREATE_INFO};
    sci.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT
                   | XR_SWAPCHAIN_USAGE_SAMPLED_BIT;
    sci.format = st->format;
    sci.width = cw;
    sci.height = ch;
    sci.faceCount = 1;
    sci.arraySize = 1;
    sci.mipCount = 1;
    sci.sampleCount = 1;
    XrResult r = g_xrCreateSwapchain(session, &sci, &st->swapchain);
    if (r != XR_SUCCESS) {
        Log("xrCreateSwapchain fehlgeschlagen (%d)", (int)r);
        return false;
    }
    uint32_t imgCount = 0;
    if (g_xrEnumerateSwapchainImages(st->swapchain, 0, &imgCount, nullptr) != XR_SUCCESS
        || imgCount == 0) {
        Log("keine Swapchain-Images");
        return false;
    }
    st->images.resize(imgCount);
    for (auto& img : st->images) img.type = XR_TYPE_SWAPCHAIN_IMAGE_D3D11_KHR;
    if (g_xrEnumerateSwapchainImages(st->swapchain, imgCount, &imgCount,
            reinterpret_cast<XrSwapchainImageBaseHeader*>(st->images.data())) != XR_SUCCESS) {
        Log("xrEnumerateSwapchainImages (zweiter Durchlauf) fehlgeschlagen");
        return false;
    }
    ID3D11Texture2D* tex = st->images[0].texture;
    if (!tex) { Log("Swapchain-Image ohne Textur"); return false; }
    tex->GetDevice(&st->device);
    if (st->device) st->device->GetImmediateContext(&st->context);
    if (!st->context) { Log("kein Immediate Context"); return false; }
    st->texW = cw;
    st->texH = ch;
    st->pixels.assign(static_cast<size_t>(cw) * ch * 4, 0xFF);
    st->lastFrame = 0xFFFFFFFFu;
    return true;
}

static void InitOverlayImpl(XrSession session, OverlayState* st) {
    st->initialized = true;
    st->ok = false;
    Log("xrEndFrame zum ersten Mal gesehen - Overlay-Init startet");

    // Nullzeiger-Schutz: Ohne aufgeloeste Runtime-Funktionen wuerde der erste
    // Aufruf den Prozess crashen statt kontrolliert abzubrechen.
    if (!g_xrEnumerateSwapchainFormats || !g_xrCreateSwapchain
        || !g_xrDestroySwapchain
        || !g_xrEnumerateSwapchainImages || !g_xrAcquireSwapchainImage
        || !g_xrWaitSwapchainImage || !g_xrReleaseSwapchainImage
        || !g_xrCreateReferenceSpace || !g_nextEndFrame) {
        Log("Runtime-Funktionen nicht aufgeloest - Overlay-Init abgebrochen");
        return;
    }

    Log("Init 1/7: Formate abfragen");
    uint32_t count = 0;
    if (g_xrEnumerateSwapchainFormats(session, 0, &count, nullptr) != XR_SUCCESS
        || count == 0) {
        Log("keine Swapchain-Formate");
        return;
    }
    Log("Formate gefunden: %u", count);
    std::vector<int64_t> formats(count);
    if (g_xrEnumerateSwapchainFormats(session, count, &count, formats.data()) != XR_SUCCESS) {
        Log("Formate-Aufruf (zweiter Durchlauf) fehlgeschlagen");
        return;
    }

    int64_t chosen = 0;
    auto prefer = [&](int64_t f) {
        if (chosen) return;
        for (int64_t x : formats) if (x == f) { chosen = x; return; }
    };
    prefer(DXGI_FORMAT_B8G8R8A8_UNORM_SRGB);  // 91
    prefer(DXGI_FORMAT_B8G8R8A8_UNORM);       // 87
    prefer(DXGI_FORMAT_R8G8B8A8_UNORM_SRGB);  // 29
    prefer(DXGI_FORMAT_R8G8B8A8_UNORM);       // 28
    if (!chosen) { Log("kein BGRA/RGBA-Format gefunden"); return; }
    Log("Texturformat gewaehlt: %lld", (long long)chosen);

    st->format = chosen;
    TryOpenShm(st);
    uint32_t cw = kTexWidth, ch = kTexHeight;
    ShmCanvasSize(st, cw, ch);
    Log("Init 2-4/7: Leinwand %ux%u (Format %lld) anlegen",
        cw, ch, (long long)chosen);
    if (!CreateCanvasImpl(session, st, cw, ch)) return;
    Log("Swapchain mit %u Images bereit", (uint32_t)st->images.size());

    // Fester Referenzraum (LOCAL) fuer die PoC-Tafel
    Log("Init 5/7: Referenzraum erstellen");
    XrReferenceSpaceCreateInfo rsci{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    rsci.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    rsci.poseInReferenceSpace = XrPosef{{0, 0, 0, 1}, {0.f, 0.f, 0.f}};
    if (g_xrCreateReferenceSpace(session, &rsci, &st->space) != XR_SUCCESS) {
        Log("xrCreateReferenceSpace fehlgeschlagen");
        st->space = XR_NULL_HANDLE;
    }
    if (st->space == XR_NULL_HANDLE) {
        Log("kein Referenzraum - Overlay-Init abgebrochen (Tafel bleibt aus)");
        return;
    }

    Log("Init 6/7: Bildpuffer liegt in der Leinwand (%ux%u)", st->texW, st->texH);

    st->quad.type = XR_TYPE_COMPOSITION_LAYER_QUAD;
    st->quad.next = nullptr;
    st->quad.layerFlags = 0;
    st->quad.space = st->space;
    st->quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
    st->quad.subImage.swapchain = st->swapchain;
    st->quad.subImage.imageRect = {{0, 0}, {int32_t(st->texW), int32_t(st->texH)}};
    st->quad.subImage.imageArrayIndex = 0;
    st->quad.pose.orientation = {0, 0, 0, 1};
    ApplyShmPose(st);

    Log("Init 7/7: Quad vorbereitet");
    st->ok = true;
    Log("Overlay-Init OK - Tafel wird ab jetzt eingereicht");
}

// Bild in die Swapchain schreiben. Wird pro xrEndFrame aufgerufen.
static void UpdateTextureImpl(XrSession session, OverlayState* st) {
    if (!st->ok || !st->swapchain) return;
    TryOpenShm(st);
    // PitBoss kann die Leinwand-Groesse aendern (z. B. andere Aufloesung):
    // Dann wird die Swapchain in der neuen Groesse neu angelegt.
    uint32_t cw = 0, ch = 0;
    ShmCanvasSize(st, cw, ch);
    if (cw != st->texW || ch != st->texH) {
        Log("Leinwand-Groesse geaendert: %ux%u - Swapchain neu anlegen", cw, ch);
        g_xrDestroySwapchain(st->swapchain);
        st->swapchain = XR_NULL_HANDLE;
        if (!CreateCanvasImpl(session, st, cw, ch)) {
            Log("Swapchain-Neuaufbau fehlgeschlagen - Tafel deaktiviert");
            st->ok = false;
            return;
        }
        st->quad.subImage.swapchain = st->swapchain;
        st->quad.subImage.imageRect = {{0, 0}, {int32_t(st->texW), int32_t(st->texH)}};
    }
    ApplyShmPose(st);
    // Performance: Solange PitBoss kein neues Bild geschickt hat (gleicher
    // frame-Zaehler), bleibt die Textur unangetastet. Nur im Testmuster-Modus
    // (ohne PitBoss) wird jede Frame gezeichnet, damit der Balken wandert.
    if (ShmValid(st) && st->shmHeader->frame == st->lastFrame) return;
    uint32_t idx = 0;
    if (g_xrAcquireSwapchainImage(st->swapchain, nullptr, &idx) != XR_SUCCESS)
        return;
    XrSwapchainImageWaitInfo wi{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
    wi.timeout = XR_INFINITE_DURATION;
    if (g_xrWaitSwapchainImage(st->swapchain, &wi) != XR_SUCCESS) {
        g_xrReleaseSwapchainImage(st->swapchain, nullptr);
        return;
    }
    FillPixels(st);
    if (ShmValid(st)) st->lastFrame = st->shmHeader->frame;
    // UpdateSubresource auf den Immediate Context des Spiels.
    st->context->UpdateSubresource(
        st->images[idx].texture, 0, nullptr,
        st->pixels.data(), st->texW * 4, 0);
    g_xrReleaseSwapchainImage(st->swapchain, nullptr);
}

// ---------------------------------------------------------------------------
// Absturz-Schutz: Ein Fehler im Overlay darf das Spiel niemals mitreissen.
// __try/__except verlangt Funktionen ohne C++-Objekte mit Destruktor, deshalb
// liegt die Logik in den *Impl-Funktionen. Die Guards fangen Ausnahmen ab,
// loggen Code und Adresse und schalten die Tafel kontrolliert aus.
// ---------------------------------------------------------------------------

static void InitOverlay(XrSession session, OverlayState* st) {
    __try {
        InitOverlayImpl(session, st);
    } __except (Log("AUSNAHME 0x%08lX in Overlay-Init (Adresse %p) - Tafel deaktiviert",
                    (unsigned long)GetExceptionCode(),
                    GetExceptionInformation()->ExceptionRecord->ExceptionAddress),
                EXCEPTION_EXECUTE_HANDLER) {
        st->initialized = true;
        st->ok = false;
    }
}

static void UpdateTexture(XrSession session, OverlayState* st) {
    __try {
        UpdateTextureImpl(session, st);
    } __except (st->ok = false,
                Log("AUSNAHME 0x%08lX in UpdateTexture (Adresse %p) - Tafel deaktiviert",
                    (unsigned long)GetExceptionCode(),
                    GetExceptionInformation()->ExceptionRecord->ExceptionAddress),
                EXCEPTION_EXECUTE_HANDLER) {
    }
}

// ---------------------------------------------------------------------------
// xrEndFrame-Hook
// ---------------------------------------------------------------------------

static XrResult XRAPI_PTR LayerEndFrame(XrSession session,
                                        const XrFrameEndInfo* frameEndInfo) {
    std::lock_guard<std::mutex> lock(g_stateMutex);

    OverlayState* st = &g_sessions[session];
    if (!st->initialized) InitOverlay(session, st);

    bool showQuad = st->ok;
    if (showQuad) UpdateTexture(session, st);

    std::vector<const XrCompositionLayerBaseHeader*> layers(
        frameEndInfo->layers, frameEndInfo->layers + frameEndInfo->layerCount);
    if (showQuad) {
        layers.push_back(
            reinterpret_cast<const XrCompositionLayerBaseHeader*>(&st->quad));
    }
    XrFrameEndInfo fe = *frameEndInfo;
    fe.layerCount = static_cast<uint32_t>(layers.size());
    fe.layers = layers.data();
    return g_nextEndFrame(session, &fe);
}

// ---------------------------------------------------------------------------
// Loader-Verhandlung
// ---------------------------------------------------------------------------

// Vorwaertsdeklaration: openxr_loader_negotiation.h deklariert
// xrCreateApiLayerInstance nur bei definiertem XR_EXTENSION_PROTOTYPES
// (nicht gesetzt). xrNegotiateLoaderApiLayerInterface unten referenziert die
// Funktion, bevor sie im Quelltext definiert wird - ohne Deklaration
// compiliert MSVC das nicht (C2065).
extern "C" PVR_EXPORT XrResult XRAPI_CALL xrCreateApiLayerInstance(
        const XrInstanceCreateInfo* createInfo,
        const XrApiLayerCreateInfo* apiLayerInfo,
        XrInstance* instance);

extern "C" PVR_EXPORT XrResult XRAPI_PTR LayerGetInstanceProcAddr(
        XrInstance instance, const char* name, PFN_xrVoidFunction* function) {
    if (!name || !function) return XR_ERROR_VALIDATION_FAILURE;
    if (!g_targetProcess) g_targetProcess = IsRaceRoomProcess();
    if (g_targetProcess && strcmp(name, "xrEndFrame") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(&LayerEndFrame);
        return XR_SUCCESS;
    }
    return g_nextGPA(instance, name, function);
}

// Schnittstelle, die der aktuelle Loader ZUERST aufruft. Der Loader startet
// danach die klassische xrCreateApiLayerInstance-Kette (unten) mit dem
// hier angekuendigten createApiLayerInstance.
extern "C" PVR_EXPORT XrResult XRAPI_CALL xrNegotiateLoaderApiLayerInterface(
        const XrNegotiateLoaderInfo* loaderInfo,
        const char* layerName,
        XrNegotiateApiLayerRequest* apiLayerRequest) {
    if (!loaderInfo || !layerName || !apiLayerRequest) {
        return XR_ERROR_VALIDATION_FAILURE;
    }
    if (loaderInfo->structType != XR_LOADER_INTERFACE_STRUCT_LOADER_INFO
        || loaderInfo->minInterfaceVersion > XR_CURRENT_LOADER_API_LAYER_VERSION) {
        return XR_ERROR_VALIDATION_FAILURE;
    }
    Log("xrNegotiateLoaderApiLayerInterface: Layer '%s'", layerName);

    apiLayerRequest->structType = XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST;
    apiLayerRequest->structVersion = XR_API_LAYER_INFO_STRUCT_VERSION;
    apiLayerRequest->structSize = sizeof(XrNegotiateApiLayerRequest);
    apiLayerRequest->layerInterfaceVersion = XR_CURRENT_LOADER_API_LAYER_VERSION;
    apiLayerRequest->layerApiVersion = XR_CURRENT_API_VERSION;
    apiLayerRequest->getInstanceProcAddr = &LayerGetInstanceProcAddr;
    apiLayerRequest->createApiLayerInstance = &xrCreateApiLayerInstance;
    return XR_SUCCESS;
}

extern "C" PVR_EXPORT XrResult XRAPI_CALL xrCreateApiLayerInstance(
        const XrInstanceCreateInfo* createInfo,
        const XrApiLayerCreateInfo* apiLayerInfo,
        XrInstance* instance) {
    if (!createInfo || !apiLayerInfo || !instance) {
        return XR_ERROR_VALIDATION_FAILURE;
    }
    if (apiLayerInfo->structType != XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO
        || apiLayerInfo->structVersion != XR_API_LAYER_CREATE_INFO_STRUCT_VERSION
        || apiLayerInfo->nextInfo == nullptr
        || apiLayerInfo->nextInfo->nextCreateApiLayerInstance == nullptr
        || apiLayerInfo->nextInfo->nextGetInstanceProcAddr == nullptr) {
        return XR_ERROR_VALIDATION_FAILURE;
    }

    if (!g_targetProcess) g_targetProcess = IsRaceRoomProcess();
    Log("xrCreateApiLayerInstance aufgerufen (Zielprozess=%d)",
        g_targetProcess ? 1 : 0);

    // Unsere Kette: naechste Instanz-Schoepfung und GPA merken,
    // danach eigenen Eintrag aus der nextInfo-Kette herausnehmen.
    PFN_xrCreateApiLayerInstance nextCreate =
        apiLayerInfo->nextInfo->nextCreateApiLayerInstance;
    g_nextGPA = apiLayerInfo->nextInfo->nextGetInstanceProcAddr;

    XrApiLayerCreateInfo nextInfo = *apiLayerInfo;
    nextInfo.nextInfo = apiLayerInfo->nextInfo->next;
    nextInfo.structSize -= sizeof(XrApiLayerNextInfo);

    // XR_KHR_D3D11_enable nur im Zielprozess anfordern, damit wir
    // Swapchain-Images lesen koennen (andere Apps unangetastet lassen).
    XrInstanceCreateInfo ci = *createInfo;
    std::vector<const char*> exts(
        createInfo->enabledExtensionNames,
        createInfo->enabledExtensionNames + createInfo->enabledExtensionCount);
    bool hasD3D11 = false;
    for (const char* e : exts)
        if (e && strcmp(e, XR_KHR_D3D11_ENABLE_EXTENSION_NAME) == 0) hasD3D11 = true;
    if (!hasD3D11 && g_targetProcess) exts.push_back(XR_KHR_D3D11_ENABLE_EXTENSION_NAME);
    ci.enabledExtensionNames = exts.data();
    ci.enabledExtensionCount = static_cast<uint32_t>(exts.size());

    XrResult res = nextCreate(&ci, &nextInfo, instance);
    Log("nextCreateApiLayerInstance: Ergebnis %d (%u Erweiterungen)",
        (int)res, ci.enabledExtensionCount);
    if (XR_FAILED(res)) return res;

    g_instance = *instance;

    // Alle benoetigten Runtime-Funktionen aufloesen. WICHTIG:
    // xrGetInstanceProcAddr erwartet die OFFIZIELLEN OpenXR-Namen. Ein Makro
    // ueber #fn wuerde den Variablennamen ("g_xrEnumerateSwapchainFormats")
    // uebergeben - die Funktion wird dann nicht gefunden, der Zeiger bleibt
    // null und der Overlay-Init scheitert beim ersten Aufruf (Vorfall
    // 07.11.2026: Praxistest-Log brach nach "Overlay-Init startet" ab).
    struct GpaEntry { const char* name; PFN_xrVoidFunction* target; };
    GpaEntry gpaTable[] = {
        {"xrEnumerateSwapchainFormats",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrEnumerateSwapchainFormats)},
        {"xrCreateSwapchain",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrCreateSwapchain)},
        {"xrDestroySwapchain",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrDestroySwapchain)},
        {"xrEnumerateSwapchainImages",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrEnumerateSwapchainImages)},
        {"xrAcquireSwapchainImage",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrAcquireSwapchainImage)},
        {"xrWaitSwapchainImage",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrWaitSwapchainImage)},
        {"xrReleaseSwapchainImage",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrReleaseSwapchainImage)},
        {"xrCreateReferenceSpace",
         reinterpret_cast<PFN_xrVoidFunction*>(&g_xrCreateReferenceSpace)},
    };
    for (const GpaEntry& e : gpaTable) {
        XrResult gpaResult = g_nextGPA(g_instance, e.name, e.target);
        if (XR_FAILED(gpaResult)) {
            Log("Aufloesung fehlgeschlagen: %s (%d)", e.name, (int)gpaResult);
        }
    }
    if (g_targetProcess) {
        g_nextGPA(g_instance, "xrEndFrame",
                  reinterpret_cast<PFN_xrVoidFunction*>(&g_nextEndFrame));
        Log("xrEndFrame-Hook installiert");
    }

    return res;
}

// ---------------------------------------------------------------------------
// DllMain
// ---------------------------------------------------------------------------

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        char proc[MAX_PATH] = {0};
        GetModuleFileNameA(nullptr, proc, MAX_PATH);
        Log("Layer-DLL geladen, Prozess: %s", proc);
    }
    if (reason == DLL_PROCESS_DETACH) {
        std::lock_guard<std::mutex> lock(g_stateMutex);
        for (auto& kv : g_sessions) CloseShm(&kv.second);
        g_sessions.clear();
        Log("Layer-DLL entladen");
    }
    return TRUE;
}
