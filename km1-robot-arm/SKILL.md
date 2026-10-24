---
name: km1-robot-arm
description: 用 Python + pyserial 驱动 KM1 / Yeahbot / YHKPZAR 六轴机械臂（ESP32-S3，6 舵机）。触发词：机械臂、KM1、Yeahbot、YHKPZAR、舵机控制、PWM、动作组、$DGS、$DGT、串口控制机械臂、机械臂不动、waiting for download、机械臂抓取。含协议速查、连接铁律、动作序列与故障排查。
---

# KM1 机械臂 Python 控制

协议族 **Yeahbot / YHKPZAR** · 主控 ESP32-S3 · 6 路舵机 (0~5) · USB CDC 虚拟串口 · 115200。
固件为 Mixly 图形化生成，动作存于 W25Q64 闪存 (SPI)。

## 零、三条铁律（先看这个，90% 的坑都在这）

1. **必须 `dtr=False` + `rts=False`**：否则 ESP32-S3 被拉进下载模式，串口只吐 `waiting for download`，固件压根没跑，任何指令都无响应。
2. **结束符不能错**：命令/动作模式以 `!` 结尾，批量模式以 `}` 结尾，存储模式以 `>` 结尾。少一个符号 = 没发。
3. **动手前先 `$DST!`**：固件上电会自动播放默认动作组，不停掉的话你发的单舵机指令会被它抢回中位。

## 一、何时触发

- 要写/改机械臂控制代码、动作编排脚本
- 机械臂不动、乱码、`could not open port`、`waiting for download`
- 要查协议指令格式（`$DGS` / `$DGT` / `#003P1500T0500!`）、角度 PWM 换算
- 要从固件里 dump 出预设动作组数据

## 二、硬件与角度换算

| 项目 | 规格 |
|---|---|
| 主控 | ESP32-S3 |
| 舵机 | 6 个（编号 `000`~`005`） |
| PWM 范围 | 500 ~ 2500（微秒） |
| 中位 90° | PWM = 1500 |
| 通信 | USB 虚拟串口 (USB CDC)，默认 115200 |

```
PWM = 500 → 0°    PWM = 1500 → 90° (中位)    PWM = 2500 → 180°

角度 → PWM:  PWM = 500 + 角度 × 2000/180
PWM → 角度:  角度 = (PWM - 500) × 180/2000
```

```python
def angle_to_pwm(angle: int) -> int:
    return round(500 + angle * 2000 / 180)

def pwm_to_angle(pwm: int) -> int:
    return round((pwm - 500) * 180 / 2000)
```

> 换算是**线性近似**。真机机械限位常有偏差，别直接给 0 / 180 极限值，先用 10°~170° 试。

## 三、连接（最关键的一步）

```python
import serial

ser = serial.Serial()
ser.port = 'COM3'          # Windows: 设备管理器里看；Linux: /dev/ttyUSB0 或 /dev/ttyACM0
ser.baudrate = 115200
ser.dtr = False            # 必须禁用，否则进下载模式
ser.rts = False            # 必须禁用
ser.timeout = 0.1
ser.open()
```

| 现象 | 原因 | 解决 |
|---|---|---|
| `SerialException: could not open port` | 端口被占用 | 关掉其他串口软件/上一个没退出的脚本 |
| 只输出 `waiting for download` | DTR/RTS 触发下载模式 | `dtr=False, rts=False`，然后**重新插拔 USB** |
| 发指令无响应 | 结束符不对 | 检查是否以 `!` 结尾（批量是 `}`） |
| 端口找不到 | 驱动未装 | 装 CH340 / CP210x 驱动 |

## 四、协议详解

### 4.1 模式前缀

| 首字符 | 模式 | 结束符 | 用途 |
|---|---|---|---|
| `$` | 命令模式 | `!` | 执行动作组、控制逻辑 |
| `#` | 动作模式 | `!` | 控制单个舵机 |
| `{` | 批量模式 | `}` | 同时控制多个舵机 |
| `<` | 存储模式 | `>` | 保存动作到闪存 |

### 4.2 命令（`$` 前缀）

```
$RST!                 重启 ESP32 控制板
$DST!                 停止所有正在执行的动作
$DST:1000!            延时 1000ms（注意：只差一个冒号，别和 $DST! 混）
$DGS:3!               执行第 3 组预设动作
$DGT:1-5,1!           执行 1~5 组，各 1 次
$KMS:x,y,z,速度!      运动学模式移动（需先开启 KMS 初始化）
```

### 4.3 单舵机（`#` 前缀）

格式固定 3+4+4 位零填充：`#索引P脉宽T时间!`

| 字段 | 范围 | 示例 |
|---|---|---|
| 索引 | `000`~`005` | `003` = 舵机 3 |
| 脉宽 | `0500`~`2500` | `1500` = 中位 |
| 时间(ms) | `0000`~`9999` | `0500` = 500ms 走完 |

```
#003P1500T0500!    舵机3 → 中位(90°)，500ms 完成
#001P2000T0800!    舵机1 → PWM 2000，800ms 完成
#000P0500T1000!    舵机0 → 0° 极限，1000ms 完成
```

### 4.4 批量（`{` 前缀）

把多个 `#` 指令拼在 `{` 与 `}` 之间，表示**同时**运动：

```
{#000P1500T0500!#001P2000T0500!#002P1500T0500!}
```

### 4.5 返回数据格式

```
$DST!                      ← 发送
#255PDST!                  ← 回显（停止动作，255 是特殊索引）

$DGS:3!                    ← 发送
{G0003#000P1500T1800!...}  ← 动作组详情回显

$DGT:10-19,1!              ← 发送
{G0010#000P1500T1500!...}  ← 第 10 组
{G0011#000P1500T1500!...}  ← 第 11 组
@GroupDone!                ← 全部执行完毕（**这是最好的同步点**）
```

> 判定动作是否做完，**认 `@GroupDone!`**，别用 `time.sleep` 硬等。

## 五、最小可用控制类

```python
import time
import serial


class RobotArm:
    """KM1 机械臂控制（Yeahbot/YHKPZAR 协议）"""

    def __init__(self, port: str, baud: int = 115200):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baud
        self.ser.dtr = False          # 铁律 1
        self.ser.rts = False
        self.ser.timeout = 0.1
        self.ser.open()
        print(f'[OK] 已连接 {port} @ {baud}')

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def send(self, cmd: str):
        # 三种结束符都要放过，否则批量指令会被错加 '!'
        if not cmd.endswith(('!', '}', '>')):
            cmd += '!'
        self.ser.write((cmd + '\n').encode('utf-8'))
        print(f'[TX] {cmd}')

    def wait_response(self, timeout: float = 2.0, until: str | None = None) -> list:
        """读返回；给了 until 就提前退出（推荐传 '@GroupDone!'）"""
        lines, t0 = [], time.time()
        while time.time() - t0 < timeout:
            if self.ser.in_waiting:
                data = self.ser.read(self.ser.in_waiting)
                for ln in data.decode('utf-8', errors='replace').split('\n'):
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
                        if until and until in ln:
                            return lines
            time.sleep(0.02)
        return lines

    def set_servo(self, index: int, pwm: int, duration: int = 500):
        self.send(f'#{index:03d}P{pwm:04d}T{duration:04d}!')

    def set_all_servos(self, pwms: list[int], duration: int = 500):
        body = ''.join(f'#{i:03d}P{pwms[i]:04d}T{duration:04d}!' for i in range(len(pwms)))
        self.send('{' + body + '}')

    def exec_group(self, group_id: int):
        self.send(f'$DGS:{group_id}!')

    def play_groups(self, start: int, end: int, times: int = 1):
        self.send(f'$DGT:{start}-{end},{times}!')

    def stop(self):
        self.send('$DST!')

    def delay(self, ms: int):
        self.send(f'$DST:{ms}!')

    def home(self):
        self.set_all_servos([1500] * 6)


if __name__ == '__main__':
    arm = RobotArm('COM7')
    arm.stop()                 # 铁律 3：先停默认动作
    time.sleep(0.5)
    arm.home()
    arm.set_servo(3, angle_to_pwm(135), 500)
    arm.wait_response(until='@GroupDone!')
    arm.close()
```

## 六、动作序列编排

```python
def play_sequence(arm, actions: list[dict]):
    """actions 示例：
    [{'type':'servo','index':3,'pwm':1500,'time':500},
     {'type':'group','id':3},
     {'type':'home'},
     {'type':'delay','ms':1000},
     {'type':'all','pwms':[1500]*6,'time':500},
     {'type':'stop'}]
    """
    for a in actions:
        t = a.get('type', '')
        if t == 'servo':
            arm.set_servo(a['index'], a['pwm'], a.get('time', 500))
        elif t == 'group':
            arm.exec_group(a['id'])
        elif t == 'home':
            arm.home()
        elif t == 'all':
            arm.set_all_servos(a['pwms'], a.get('time', 500))
        elif t == 'delay':
            time.sleep(a['ms'] / 1000)
        elif t == 'stop':
            arm.stop()
```

编排要点：

- 相邻动作之间留 `0.2s` 以上，固件解析是**流式**的，挤太密会丢帧
- 单次运动 `time` 建议 **≥ 300ms**，太短舵机会抖、堵转发热
- 批量模式（`{}`）是"同时到"，串行 `#` 是"依次到"，别混用表达同一意图
- 长时间跑序列时，用后台线程读串口（`daemon=True`），否则接收缓冲区会满

## 七、探测固件里的预设动作组

```python
arm.send('$DGT:10-19,1!')
lines = arm.wait_response(timeout=15, until='@GroupDone!')
# 每行形如 {G0010#000P1500T1500!#001P2000T1500!...}
```

每行含该组 6 个舵机的目标 PWM 与时间，可据此反推这台机器人的能力范围，再自己写动作。

## 八、跨平台（Windows / Linux）

| 项目 | Windows | Linux |
|---|---|---|
| 串口路径 | `COM1`~`COM256` | `/dev/ttyUSB0`、`/dev/ttyACM0` |
| 驱动 | 需装 CH340 / CP210x | 内核自带 (cdc_acm / ch341) |
| 权限 | 普通用户即可 | 需加入 `dialout` 组 |

```bash
sudo usermod -aG dialout $USER   # 之后需重新登录（或 newgrp dialout）
```

```python
import glob
import serial.tools.list_ports


def find_arm_port():
    """按 USB 转串口芯片 VID 自动找端口"""
    for p in serial.tools.list_ports.comports():
        if p.vid in (0x1A86, 0x10C4, 0x0403, 0x2E88):  # CH340 / CP210x / FTDI / ESP32
            return p.device
    for pattern in ('/dev/ttyUSB*', '/dev/ttyACM*', 'COM*'):
        for path in sorted(glob.glob(pattern)):
            return path
    return None
```

除端口名与驱动权限外，**其余代码完全一致**（DTR/RTS、协议、换算都不变）。

## 九、故障排查

| 症状 | 排查顺序 |
|---|---|
| **舵机不动** | ① 是否先发了 `$DST!` ② PWM 是否在 500~2500 ③ 索引是否 0~5 ④ `time` 是否 ≥300ms |
| **乱码 / 无响应** | ① 波特率是否 115200 ② 结束符是否 `!`/`}`/`>` ③ 连上后先发 `$RST!` 重启 |
| **串口打不开** | 列端口确认设备在：`for p in serial.tools.list_ports.comports(): print(p.device, p.description)` |
| **进下载模式** | 日志出现 `ESP-ROM:esp32s3... waiting for download` → 设 `dtr/rts=False` + 重新插拔 USB |
| **动作被打断** | 上电默认动作组在跑 → `$DST!` 后再发新指令 |

## 十、协议速查 + 舵机映射

```
$DST!                 停止所有动作
$DGS:3!               执行第 3 组
$DGT:1-5,1!           执行 1~5 组，各 1 次
#003P1500T0500!       3 号舵机 → 1500 → 500ms
{#000P...!#001P...!}  同时控制多舵机
<位置数据>            存储动作到闪存
$RST!                 重启控制板
```

| 编号 | 关节 | 编号 | 关节 |
|---|---|---|---|
| 0 | 底座旋转（左右） | 3 | 腕部俯仰 |
| 1 | 大臂（前后） | 4 | 腕部旋转（左右） |
| 2 | 小臂（上下） | 5 | 夹爪（开合） |

## 十一、工程纪律

- **新写控制脚本，入口第一件事是 `stop()`**，否则你会以为是代码不生效
- 封装 `send()` 时**三种结束符都要放过**（`!` / `}` / `>`），只判 `!` 会把 `{...}` 拼坏
- 判定完成认 `@GroupDone!`，不要靠 `sleep(2)` 猜（组时长从几百毫秒到十几秒都有）
- 调试时把 `[TX]` 打印出来，对照协议表肉眼核一遍零填充位数
- 硬件类测试**不要手算期望值**，用 `angle_to_pwm()` 反算后打印核对
- 串口对象用完必须 `close()`，否则下次运行报"端口被占用"
