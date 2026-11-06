cmake_minimum_required(VERSION 3.20)
project(pitboss_vr_layer LANGUAGES CXX)

# PitBoss R3E - OpenXR API Layer (0.4.0.0 PoC)
# Baut XR_APILAYER_PitBossR3E_VR.dll. Nur Header + D3D11, keine Loader-Linkung:
# Der Layer verhandelt selbst mit dem OpenXR-Loader (xrCreateApiLayerInstance).

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
  openxr
  GIT_REPOSITORY https://github.com/KhronosGroup/OpenXR-SDK-Source.git
  GIT_TAG        release-1.1.45
  GIT_SHALLOW    TRUE
)
FetchContent_GetProperties(openxr)
if(NOT openxr_POPULATED)
  FetchContent_Populate(openxr)
endif()

add_library(pitboss_vr_layer SHARED pitboss_vr_layer.cpp)

target_include_directories(pitboss_vr_layer PRIVATE
  ${openxr_SOURCE_DIR}/include
  ${openxr_SOURCE_DIR}/src/loader      # xr_loader.h (XrApiLayerCreateInfo)
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
