# 一、wlcom架构简介

wlcom是一款基于wlroots的Wayland合成器，以实现高性能、高安全、易维护为目标，具有渲染性能高、安全性高、生态兼容好、功能可灵活定制、第三方依赖少等技术特性。其基本架构如下图所示：
flowchart TB
    %% 样式定义
    classDef refactor fill:#ff6b6b,stroke:#c92a2a,color:#fff,stroke-width:2px
    classDef add fill:#51cf66,stroke:#2b8a3e,color:#fff,stroke-width:2px
    classDef original fill:#f8f9fa,stroke:#adb5bd,color:#333,stroke-width:2px
    classDef support fill:#4dabf7,stroke:#1971c2,color:#fff,stroke-width:2px
    classDef appLayer fill:#d0ebff,stroke:#339af0,color:#1864ab,stroke-width:2px
    classDef subgraphStyle fill:#fff0f0,stroke:#ff6b6b,color:#333,stroke-width:1px,stroke-dasharray: 5 5
    
    %% 应用层
    app[应用层]:::appLayer
    
    %% libdrm 层
    subgraph row1["libdrm"]
        direction LR
        ext_plugin[外部插件接口库插件]:::refactor
        func_plugin[功能框架接口库插件]:::refactor
    end
    
    %% libinput 层
    subgraph row2["libinput"]
        direction LR
        sec_plugin[安全插件]:::add
        input_plugin[输入管理插件]:::add
        output_plugin[输出管理插件]:::refactor
        deco_plugin[窗口装饰插件]:::refactor
        effect_plugin[特效插件]:::add
    end
    
    %% libcairo 层
    subgraph row3["libcairo"]
        direction LR
        win_plugin[窗口管理插件]:::refactor
        render_plugin[图像渲染合成插件]:::add
    end
    
    %% libxkbcommon 层
    subgraph row4["libxkbcommon"]
        direction LR
        wlroots[wlroots]:::original
        proto_plugin[自研协议库插件]:::add
        sec_proto[安全协议]:::add
    end
    
    %% 硬件支持层
    subgraph row5["硬件支持层"]
        direction LR
        input_dev[输入设备支持]:::support
        gpu1[商用GPU支持]:::support
        gpu2[信创GPU支持]:::add
    end
    
    %% 层级关系（从上到下）
    app --> row1
    row1 --> row2
    row2 --> row3
    row3 --> row4
    row4 --> row5
    
    %% 图例
    subgraph legend["图例"]
        direction LR
        leg1[重构]:::refactor
        leg2[新增]:::add
        leg3[原始依赖]:::original
    end

# 二、wlcom代码仓库地址

代码仓库地址：
https://gitee.com/openkylin/kylin-wayland-compositor

运行时需要使用的库或程序:

● wlroots, wayland, libinput, xkbcommon

● libseat, libdrm, libsystemd, librsvg-2.0

● cairo, pango, pangocairo, pixman-1

● gbm, json-c, libudev

● xwayland, xcb (optional)

依赖安装可通过apt进行（配置了deb-src源）

apt build-dep kylin-wayland-compositor
AI写代码
编译选项见meson_options.txt，简单的编译指令:

meson setup build -Dbuildtype=debugoptimized
ninja -C build
meson install -C build --skip-subprojects
AI写代码
程序参数如下：​​​​​​​

"Usage: kylin-wlcom [options] [command]"
" -h, --help Show help message and quit.\n"
" -d, --debug Enables full logging, including debug information.\n"
" -D, --debug <options> noxwayland or logtostdout.\n"
" -s, --session <process> Run session on startup\n"
" -v, --version Show the version number and quit.\n"
" -V, --verbose Enables more verbose logging.\n"
AI写代码
通过-D参数可以方便运行时调试, 支持参数如下：​​​​​​​

-Dnoxwayland 关闭xwayland支持
-Dlogtostdout 将日志打印到stdout
-Dloginmtime 使用monotonic time输出日志
AI写代码
默认情况下，日志打印到文件$HOME/.log/kylin-wlcom.log。
