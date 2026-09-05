# Kylin-MemoryHub 桌面客户端（Qt 5 Widgets）
# 目标环境：银河麒麟 V11 / openKylin 2.x（UKUI 桌面，Qt 5.15）
# 开发验证：Windows + Qt 5.15（MSVC/MinGW）亦可构建

cmake_minimum_required(VERSION 3.16)

project(KylinMemoryHubClient VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 中文源码用 UTF-8；MSVC 需要显式 UTF-8 编译选项
if(MSVC)
    add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:/utf-8>")
endif()

set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOGEN_PARALLEL 1)

# 优先查找 Qt5；目标环境为麒麟 Qt 5.15
find_package(Qt5 5.9 REQUIRED COMPONENTS
    Core Gui Widgets Network Charts
)
find_package(Qt5 5.9 REQUIRED COMPONENTS Test)

set(CLIENT_SOURCES
    src/main.cpp
    src/AppContext.cpp
    src/api/ApiClient.cpp
    src/api/Json.cpp
    src/MainWindow.cpp
    src/widgets/PageHeader.cpp
    src/widgets/StatCard.cpp
    src/widgets/ScoreRing.cpp
    src/widgets/StatusTag.cpp
    src/widgets/JsonViewer.cpp
    src/widgets/EmptyState.cpp
    src/widgets/DetailDrawer.cpp
    src/widgets/MemoryFilterBar.cpp
    src/widgets/ConfirmDialog.cpp
    src/widgets/RoundedContainer.cpp
    src/widgets/PageStateView.cpp
    src/widgets/ProvenancePanel.cpp
    src/pages/BasePage.cpp
    src/pages/DashboardPage.cpp
    src/pages/VNextDashboardPages.cpp
    src/pages/TerminalPage.cpp
    src/pages/PreferencePage.cpp
    src/pages/KnowledgePage.cpp
    src/pages/MemoryTierPage.cpp
    src/pages/FactPage.cpp
    src/pages/SearchPage.cpp
    src/pages/ProjectionPage.cpp
    src/pages/ConflictPage.cpp
    src/pages/ForgetPages.cpp
    src/pages/SafetyPages.cpp
    src/pages/SettingsPages.cpp
)

set(CLIENT_HEADERS
    src/AppContext.h
    src/api/ApiClient.h
    src/api/Json.h
    src/MainWindow.h
    src/widgets/PageHeader.h
    src/widgets/StatCard.h
    src/widgets/ScoreRing.h
    src/widgets/StatusTag.h
    src/widgets/JsonViewer.h
    src/widgets/EmptyState.h
    src/widgets/DetailDrawer.h
    src/widgets/MemoryFilterBar.h
    src/widgets/ConfirmDialog.h
    src/widgets/RoundedContainer.h
    src/widgets/PageStateView.h
    src/widgets/ProvenancePanel.h
    src/pages/BasePage.h
    src/pages/DashboardPage.h
    src/pages/VNextDashboardPages.h
    src/pages/TerminalPage.h
    src/pages/PreferencePage.h
    src/pages/KnowledgePage.h
    src/pages/MemoryTierPage.h
    src/pages/FactPage.h
    src/pages/SearchPage.h
    src/pages/ProjectionPage.h
    src/pages/ConflictPage.h
    src/pages/ForgetPages.h
    src/pages/SafetyPages.h
    src/pages/SettingsPages.h
)

add_executable(memoryhub-client WIN32 ${CLIENT_SOURCES} ${CLIENT_HEADERS} resources/app.qrc)

target_link_libraries(memoryhub-client PRIVATE
    Qt5::Core Qt5::Gui Qt5::Widgets Qt5::Network Qt5::Charts
)

enable_testing()
add_executable(memoryhub-client-api-tests tests/ApiClientTest.cpp src/api/ApiClient.cpp src/AppContext.cpp)
target_include_directories(memoryhub-client-api-tests PRIVATE src)
target_link_libraries(memoryhub-client-api-tests PRIVATE Qt5::Core Qt5::Gui Qt5::Widgets Qt5::Network Qt5::Test)
add_test(NAME memoryhub-client-api-tests COMMAND memoryhub-client-api-tests)

if(WIN32)
    target_compile_definitions(memoryhub-client PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

# Windows 下启用高 DPI（Qt 5.6+ 已默认，这里显式声明）
if(WIN32)
    target_compile_definitions(memoryhub-client PRIVATE QT_DISABLE_DEPRECATED_BEFORE=0x050900)
endif()
