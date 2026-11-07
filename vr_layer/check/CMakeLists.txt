cmake_minimum_required(VERSION 3.20)
project(pitboss_vr_check CXX)

add_executable(pitboss_vr_check pitboss_vr_check.cpp)
target_compile_features(pitboss_vr_check PRIVATE cxx_std_17)
