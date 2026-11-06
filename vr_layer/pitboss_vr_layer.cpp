// ---------------------------------------------------------------------------
// PitBoss R3E - OpenXR API Layer "VR Overlay" (Proof of Concept, 0.4.0.0)
// ---------------------------------------------------------------------------
// Blendet eine virtuelle Tafel (Quad-Layer) in die OpenXR-Szene des Spiels
// ein. Funktioniert mit jeder OpenXR-Runtime, also ausdruecklich auch mit
// Virtual Desktop / VDXR (kein SteamVR noetig) - der Layer laeuft als
// Teil des Spielprozesses.
//
// Architektur:
//   PitBoss (Python) rendert die Overlay-Inhalte als BGRA-Bild in den
//   Shared-Memory-Puffer "Local\\PitBossR3E_VR" (Header: magic, version,
//   width, height, frame). Der Layer liest diesen Puffer und legt ihn als
//   Quad-Layer ueber die Szene. Fehlt der Puffer (PitBoss laeuft nicht),
//   zeigt der Layer ein ruhiges Testmuster - so ist der PoC ohne PitBoss
//   pruefbar ("weisse Testtafel").
//
// PoC-Einschraenkungen (dokumentiert, Ausbau in Folgeversionen):
//   - Eine Instanz, eine Session (map, aber nur erster Session aktiv).
//   - Texture-Updates ueber den Immediate Context des Spiels (D3D11).
//     Fuer den PoC akzeptiert; Ausbau auf deferred context geplant.
//   - Feste Pose im LOCAL-Raum (oben, etwas vor dem Startpunkt).
//
// Build: siehe vr_layer/CMakeLists.txt (Windows, D3D11, OpenXR-Header per
// FetchContent aus dem offiziellen Khronos SDK-Source).
// ---------------------------------------------------------------------------

#define XR_USE_PLATFORM_WIN32
#define XR_USE_GRAPHICS_API_D3D11

#include <windows.h>
#include <d3d11.h>

#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include "xr_loader.h"

#include <atomic>
#include <cstdarg>
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
// Logging (DebugView / dbgview; im Normalfall still)
// ---------------------------------------------------------------------------

static void Log(const char* fmt, ...) {
#ifdef PVR_DEBUG
    char buf[512];
    va_list args;
    va_start(args, fmt);
    _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, args);
    va_end(args);
    OutputDebugStringA("[PitBossVR] ");
    OutputDebugStringA(buf);
    OutputDebugStringA("\n");
#else
    (void)fmt;
#endif
}

// ---------------------------------------------------------------------------
// Shared-Memory-Protokoll (identisch zur Python-Seite, siehe vr_layer/README)
// ---------------------------------------------------------------------------

struct SharedHeader {
    uint32_t magic;     // 'P','B','V','R' little-endian
    uint32_t version;   // 1
    uint32_t width;
    uint32_t height;
    uint32_t frame;     // laufende Nummer, Python inkrementiert pro Bild
};
static const uint32_t kMagic = 0x52564250;  // "PBVR" little-endian
static const uint32_t kVersion = 1;
static const uint32_t kTexWidth = 512;
static const uint32_t kTexHeight = 256;

// ---------------------------------------------------------------------------
// Globaler Layer-Zustand
// ---------------------------------------------------------------------------

static XrInstance                    g_instance = XR_NULL_HANDLE;
static PFN_xrGetInstanceProcAddr     g_nextGPA = nullptr;
static PFN_xrEndFrame               g_nextEndFrame = nullptr;
static PFN_xrDestroyInstance        g_nextDestroyInstance = nullptr;

// GPA'd OpenXR-Funktionen (Runtime-seitig)
static PFN_xrEnumerateSwapchainFormats  g_xrEnumerateSwapchainFormats;
static PFN_xrCreateSwapchain           g_xrCreateSwapchain;
static PFN_xrEnumerateSwapchainImages  g_xrEnumerateSwapchainImages;
static PFN_xrAcquireSwapchainImage     g_xrAcquireSwapchainImage;
static PFN_xrWaitSwapchainImage        g_xrWaitSwapchainImage;
static PFN_xrReleaseSwapchainImage     g_xrReleaseSwapchainImage;
static PFN_xrCreateReferenceSpace      g_xrCreateReferenceSpace;
static PFN_xrDestroySwapchain          g_xrDestroySwapchain;
static PFN_xrDestroySpace              g_xrDestroySpace;

// ---------------------------------------------------------------------------
// Per-Session Overlay-Zustand
// ---------------------------------------------------------------------------

struct OverlayState {
    bool        initialized = false;   // Init versucht (egal ob erfolgreich)
    bool        ok = false;            // Overlay einsatzbereit
    XrSwapchain swapchain = XR_NULL_HANDLE;
    XrSpace     space = XR_NULL_HANDLE;
    ID3D11Device*        device = nullptr;   // no ref addiert (Lebenszeit: Spiel)
    ID3D11DeviceContext* context = nullptr;  // Immediate Context (kein Ref)
    std::vector<XrSwapchainImageD3D11KHR> images;
    XrCompositionLayerQuad quad{};
    // CPU-Puffer fuer das Bild (BGRA)
    std::vector<uint8_t> pixels;
    // Shared Memory (PitBoss)
    HANDLE      shm = nullptr;
    SharedHeader* shmHeader = nullptr;
    uint8_t*    shmPixels = nullptr;
    DWORD       shmSize = 0;
    uint32_t    lastFrameSeen = 0;
    // Testmuster-Takt
    uint64_t    tick = 0;
};

static std::mutex g_stateMutex;
static std::map<XrSession, OverlayState> g_sessions;

// ---------------------------------------------------------------------------
// Shared Memory mit PitBoss
// ---------------------------------------------------------------------------

static void CloseShm(OverlayState* st) {
    if (st->shmPixels) st->shmPixels = nullptr;
    if (st->shmHeader) st->shmHeader = nullptr;
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
    st->shmSize = 0;
}

static bool ShmValid(const OverlayState* st) {
    return st->shmHeader
        && st->shmHeader->magic == kMagic
        && st->shmHeader->version == kVersion
        && st->shmHeader->width == kTexWidth
        && st->shmHeader->height == kTexHeight;
}

// ---------------------------------------------------------------------------
// Bildinhalt: PitBoss-Frame oder Testmuster
// ---------------------------------------------------------------------------

static void FillPixels(OverlayState* st) {
    uint8_t* dst = st->pixels.data();
    const size_t rowBytes = kTexWidth * 4;
    // 1) Testmuster als Grundlage (BGRA)
    for (uint32_t y = 0; y < kTexHeight; ++y) {
        uint8_t* row = dst + y * rowBytes;
        uint8_t v = static_cast<uint8_t>(40 + (y * 120) / kTexHeight);
        for (uint32_t x = 0; x < kTexWidth; ++x) {
            uint8_t* px = row + x * 4;
            px[0] = v;            // B
            px[1] = 0x30;         // G
            px[2] = 0x30;         // R
            px[3] = 0xFF;         // A
        }
    }
    // Rahmen
    for (uint32_t x = 0; x < kTexWidth; ++x) {
        for (int e = 0; e < 3; ++e) {
            *(dst + x * 4 + 2) = 0xD0; *(dst + x * 4 + 1) = 0xD0; *(dst + x * 4) = 0xD0;
            *(dst + (kTexHeight - 1 - e) * rowBytes + x * 4 + 2) = 0xD0;
            *(dst + (kTexHeight - 1 - e) * rowBytes + x * 4 + 1) = 0xD0;
            *(dst + (kTexHeight - 1 - e) * rowBytes + x * 4) = 0xD0;
        }
    }
    for (uint32_t y = 0; y < kTexHeight; ++y) {
        for (int e = 0; e < 3; ++e) {
            uint8_t* l = dst + y * rowBytes + e * 4;
            l[2] = l[1] = l[0] = 0xD0;
            uint8_t* r = dst + y * rowBytes + (kTexWidth - 1 - e) * 4;
            r[2] = r[1] = r[0] = 0xD0;
        }
    }
    // 2) Lauftext-Streifen: wandernder Block als "Lebenszeichen"
    st->tick++;
    uint32_t bar = static_cast<uint32_t>((st->tick * 6) % (kTexWidth - 96));
    for (uint32_t y = kTexHeight - 48; y < kTexHeight - 16; ++y) {
        for (uint32_t x = bar; x < bar + 96; ++x) {
            uint8_t* px = dst + y * rowBytes + x * 4;
            px[0] = 0x60; px[1] = 0xC0; px[2] = 0x30; px[3] = 0xFF;  // gruen
        }
    }
    // 3) PitBoss-Frame uebernehmen, wenn vorhanden
    if (!st->shm) TryOpenShm(st);
    if (st->shm && ShmValid(st)) {
        memcpy(dst, st->shmPixels, kTexWidth * kTexHeight * 4);
        st->lastFrameSeen = st->shmHeader->frame;
    }
}

// ---------------------------------------------------------------------------
// Overlay-Initialisierung pro Session
// ---------------------------------------------------------------------------

static void InitOverlay(XrSession session, OverlayState* st) {
    st->initialized = true;
    st->ok = false;

    // Unterstuetzte Swapchain-Formate holen; D3D11-Formate als int64 (DXGI)
    uint32_t count = 0;
    if (g_xrEnumerateSwapchainFormats(session, 0, &count, nullptr) != XR_SUCCESS
        || count == 0) {
        Log("keine Swapchain-Formate");
        return;
    }
    std::vector<int64_t> formats(count);
    g_xrEnumerateSwapchainFormats(session, count, &count, formats.data());

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

    XrSwapchainCreateInfo sci{XR_TYPE_SWAPCHAIN_CREATE_INFO};
    sci.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT
                   | XR_SWAPCHAIN_USAGE_SAMPLED_BIT;
    sci.format = chosen;
    sci.width = kTexWidth;
    sci.height = kTexHeight;
    sci.faceCount = 1;
    sci.arraySize = 1;
    sci.mipCount = 1;
    sci.sampleCount = 1;
    if (g_xrCreateSwapchain(session, &sci, &st->swapchain) != XR_SUCCESS) {
        Log("xrCreateSwapchain fehlgeschlagen");
        return;
    }

    uint32_t imgCount = 0;
    g_xrEnumerateSwapchainImages(st->swapchain, 0, &imgCount, nullptr);
    if (imgCount == 0) { Log("keine Swapchain-Images"); return; }
    st->images.resize(imgCount);
    for (auto& img : st->images) img.type = XR_TYPE_SWAPCHAIN_IMAGE_D3D11_KHR;
    g_xrEnumerateSwapchainImages(st->swapchain, imgCount, &imgCount,
                                 reinterpret_cast<XrSwapchainImageBaseHeader*>(st->images.data()));

    // Geraet aus dem ersten Image beziehen (im Spielprozess erlaubt)
    ID3D11Texture2D* tex = st->images[0].texture;
    if (!tex) { Log("Swapchain-Image ohne Textur"); return; }
    tex->GetDevice(&st->device);
    if (st->device) st->device->GetImmediateContext(&st->context);
    if (!st->context) { Log("kein Immediate Context"); return; }

    // Fester Referenzraum (LOCAL) fuer die PoC-Tafel
    XrReferenceSpaceCreateInfo rsci{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
    rsci.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    rsci.poseInReferenceSpace = XrPosef{{0, 0, 0, 1}, {0.f, 0.f, 0.f}};
    if (g_xrCreateReferenceSpace(session, &rsci, &st->space) != XR_SUCCESS) {
        Log("xrCreateReferenceSpace fehlgeschlagen");
        st->space = XR_NULL_HANDLE;
    }

    st->pixels.assign(kTexWidth * kTexHeight * 4, 0xFF);

    st->quad.type = XR_TYPE_COMPOSITION_LAYER_QUAD;
    st->quad.next = nullptr;
    st->quad.layerFlags = 0;
    st->quad.space = st->space;
    st->quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
    st->quad.subImage.swapchain = st->swapchain;
    st->quad.subImage.imageRect = {{0, 0}, {int32_t(kTexWidth), int32_t(kTexHeight)}};
    st->quad.subImage.imageArrayIndex = 0;
    st->quad.pose.orientation = {0, 0, 0, 1};
    st->quad.pose.position = {0.f, 0.25f, -1.0f};
    st->quad.size = {0.5f, 0.25f};

    st->ok = true;
    Log("Overlay-Init OK (Session %p)", (void*)session);
}

// Bild in die Swapchain schreiben
static void UpdateTexture(OverlayState* st) {
    uint32_t idx = 0;
    if (g_xrAcquireSwapchainImage(st->swapchain, nullptr, &idx) != XR_SUCCESS)
        return;
    XrSwapchainImageWaitInfo wi{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
    wi.timeout = XR_TIMEOUT_INDEFINITE;
    if (g_xrWaitSwapchainImage(st->swapchain, &wi) != XR_SUCCESS) {
        g_xrReleaseSwapchainImage(st->swapchain, nullptr);
        return;
    }
    FillPixels(st);
    // PoC: UpdateSubresource auf den Immediate Context. Ein System-Memory-
    // Copy ist hier implizit (D3D11 legt intern einen Staging-Pfad an).
    st->context->UpdateSubresource(
        st->images[idx].texture, 0, nullptr,
        st->pixels.data(), kTexWidth * 4, 0);
    g_xrReleaseSwapchainImage(st->swapchain, nullptr);
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
    if (showQuad) UpdateTexture(st);

    std::vector<const XrCompositionLayerBaseHeader*> layers(
        frameEndInfo->layers, frameEndInfo->layers + frameEndInfo->layerCount);
    if (showQuad) {
        layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&st->quad));
    }
    XrFrameEndInfo fe = *frameEndInfo;
    fe.layerCount = static_cast<uint32_t>(layers.size());
    fe.layers = layers.data();
    return g_nextEndFrame(session, &fe);
}

// ---------------------------------------------------------------------------
// Loader-Verhandlung (Interface v1)
// ---------------------------------------------------------------------------

extern "C" PVR_EXPORT XrResult XRAPI_PTR LayerGetInstanceProcAddr(XrInstance instance,
                                                   const char* name,
                                                   PFN_xrVoidFunction* function) {
    if (!name || !function) return XR_ERROR_VALIDATION_FAILURE;
    if (strcmp(name, "xrEndFrame") == 0) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(&LayerEndFrame);
        return XR_SUCCESS;
    }
    if (strcmp(name, "xrDestroyInstance") == 0 && g_nextDestroyInstance) {
        *function = reinterpret_cast<PFN_xrVoidFunction>(g_nextDestroyInstance);
        return XR_SUCCESS;
    }
    return g_nextGPA(instance, name, function);
}

extern "C" PVR_EXPORT XrResult XRAPI_ENTRY xrCreateApiLayerInstance(const XrInstanceCreateInfo* createInfo,
                                              const XrApiLayerCreateInfo* apiLayerInfo,
                                              XrInstance* instance) {
    if (!createInfo || !apiLayerInfo || !instance) return XR_ERROR_VALIDATION_FAILURE;

    PFN_xrCreateInstance nextCreateInstance = nullptr;
    apiLayerInfo->nextGetInstanceProcAddr(
        nullptr, "xrCreateInstance",
        reinterpret_cast<PFN_xrVoidFunction*>(&nextCreateInstance));
    if (!nextCreateInstance) return XR_ERROR_INITIALIZATION_FAILED;

    // XR_KHR_D3D11_enable anfordern, damit wir Swapchain-Images lesen koennen
    XrInstanceCreateInfo ci = *createInfo;
    std::vector<const char*> exts(
        createInfo->enabledExtensionNames,
        createInfo->enabledExtensionNames + createInfo->enabledExtensionCount);
    bool hasD3D11 = false;
    for (const char* e : exts)
        if (strcmp(e, XR_KHR_D3D11_ENABLE_EXTENSION_NAME) == 0) hasD3D11 = true;
    if (!hasD3D11) exts.push_back(XR_KHR_D3D11_ENABLE_EXTENSION_NAME);
    ci.enabledExtensionNames = exts.data();
    ci.enabledExtensionCount = static_cast<uint32_t>(exts.size());

    XrResult res = nextCreateInstance(&ci, instance);
    if (XR_FAILED(res)) return res;

    g_instance = *instance;
    g_nextGPA = apiLayerInfo->nextGetInstanceProcAddr;

    // Alle benoetigten Runtime-Funktionen GPA-en
    #define GPA(fn) \
        g_nextGPA(g_instance, #fn, reinterpret_cast<PFN_xrVoidFunction*>(&fn))
    GPA(g_xrEnumerateSwapchainFormats);
    GPA(g_xrCreateSwapchain);
    GPA(g_xrEnumerateSwapchainImages);
    GPA(g_xrAcquireSwapchainImage);
    GPA(g_xrWaitSwapchainImage);
    GPA(g_xrReleaseSwapchainImage);
    GPA(g_xrCreateReferenceSpace);
    GPA(g_xrDestroySwapchain);
    GPA(g_xrDestroySpace);
    g_nextGPA(g_instance, "xrEndFrame",
              reinterpret_cast<PFN_xrVoidFunction*>(&g_nextEndFrame));
    g_nextGPA(g_instance, "xrDestroyInstance",
              reinterpret_cast<PFN_xrVoidFunction*>(&g_nextDestroyInstance));
    #undef GPA

    Log("Layer-Instanz erstellt (%u Erweiterungen)", ci.enabledExtensionCount);
    return res;
}

// ---------------------------------------------------------------------------
// DllMain
// ---------------------------------------------------------------------------

BOOL APIENTRY DllMain(HMODULE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_DETACH) {
        std::lock_guard<std::mutex> lock(g_stateMutex);
        for (auto& kv : g_sessions) CloseShm(&kv.second);
        g_sessions.clear();
    }
    return TRUE;
}
