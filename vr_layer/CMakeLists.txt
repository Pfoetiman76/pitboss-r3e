cmake_minimum_required(VERSION 3.20)
project(pitboss_vr_layer LANGUAGES CXX)

# PitBoss R3E - OpenXR API Layer (0.4.0.0 PoC)
# Baut XR_APILAYER_PitBossR3E_VR.dll.
#
# OpenXR-Header: Die vier noetigen Public-Header des Khronos OpenXR-SDK
# (release-1.1.45, Apache-2.0/MIT) werden beim Konfigurieren einmalig in den
# Build-Ordner geladen. Kein SDK-Subprojekt, keine Submodule, keine
# Generierung noetig - der PoC braucht nur die Header.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PVR_OPENXR_DIR ${CMAKE_BINARY_DIR}/third_party/openxr)
set(PVR_OPENXR_BASE
    "https://raw.githubusercontent.com/KhronosGroup/OpenXR-SDK/release-1.1.45/include/openxr")

foreach(hdr openxr_platform_defines.h openxr.h openxr_platform.h openxr_loader_negotiation.h)
  if(NOT EXISTS ${PVR_OPENXR_DIR}/${hdr})
    message(STATUS "Lade OpenXR-Header: ${hdr}")
    file(DOWNLOAD ${PVR_OPENXR_BASE}/${hdr} ${PVR_OPENXR_DIR}/${hdr}
         SHOW_PROGRESS STATUS dl_status)
    list(GET dl_status 0 dl_code)
    if(NOT dl_code EQUAL 0)
      message(FATAL_ERROR "Download fehlgeschlagen fuer ${hdr}: ${dl_status}")
    endif()
  endif()
endforeach()

add_library(pitboss_vr_layer SHARED pitboss_vr_layer.cpp)

target_include_directories(pitboss_vr_layer PRIVATE
  ${CMAKE_BINARY_DIR}/third_party
)

target_compile_definitions(pitboss_vr_layer PRIVATE
  XR_USE_PLATFORM_WIN32
  XR_USE_GRAPHICS_API_D3D11
  WIN32_LEAN_AND_MEAN
  NOMINMAX
  $<$<CONFIG:Debug>:PVR_DEBUG>
)

target_link_libraries(pitboss_vr_layer PRIVATE d3d11)

set_target_properties(pitboss_vr_layer PROPERTIES
  OUTPUT_NAME "XR_APILAYER_PitBossR3E_VR"
)

# Manifest neben die DLL kopieren (zusammen gehoeren sie zusammen)
add_custom_command(TARGET pitboss_vr_layer POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
          ${CMAKE_CURRENT_SOURCE_DIR}/pitboss_vr_layer.json
          $<TARGET_FILE_DIR:pitboss_vr_layer>/pitboss_vr_layer.json)
