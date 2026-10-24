---
name: km1-robot-arm
description: 用 Python + pyserial 驱动松甲机器人 KM1 / Yeahbot / YHKPZAR 六轴机械臂（6 舵机，115200）。覆盖 KM1 的三款控制器——三款串口指令完全兼容，只有 DTR/RTS 配置不同。触发词：机械臂、KM1、Yeahbot、YHKPZAR、松甲、舵机控制、PWM、动作组、$DGS、$DGT、串口控制机械臂、机械臂不动、waiting for download、机械臂抓取。含协议速查、三款控制器差异、自动探测、动作序列与故障排查。
---

# KM1 机械臂 Python 控制

松甲机器人 **KM1** 六轴机械臂 · 协议族 **Yeahbot / YHKPZAR** · 6 路舵机 (0~5) · USB 虚拟串口 · 115200。
固件为 Mixly 图形化生成，动作存于 W25Q64 闪存 (SPI)。

> **支持 KM1 的三款控制器。** 三款的串口指令**完全兼容**——`#003P1500T0500!`、`$DGS:3!`、`{...}` 在任何一款上照发即可，协议、角度换算、返回格式全都一样。
> **唯一差异是开串口时 `dtr` / `rts` 的两个取值**，见 [§3.1](#31-三款控制器命令完全一样只有-dtrrts-不同)。代码逻辑不需要按型号分支。

## 零、三条铁律（先看这个，90% 的坑都在这）

1. **`dtr` / `rts` 按控制器型号配**：这是三款控制器**唯一**的差异（§3.1）。配错只有两种表现——串口只吐 `waiting for download`（板子被按进下载模式），或串口能开但发指令毫无回应（板子被按在复位里）。不确定型号就跑 §3.3 的自动探测。
2. **结束符不能错**：命令/动作模式以 `!` 结尾，批量模式以 `}` 结尾，存储模式以 `>` 结尾。少一个符号 = 没发。
3. **动手前先 `$DST!`**：固件上电会自动播放默认动作组，不停掉的话你发的单舵机指令会被它抢回中位。

## 一、何时触发

- 要写/改机械臂控制代码、动作编排脚本
- 机械臂不动、乱码、`could not open port`、`waiting for download`
- 要查协议指令格式（`$DGS` / `$DGT` / `#003P1500T0500!`）、角度 PWM 换算
- 换了一台 KM1（控制器型号可能不同），代码跑不通
- 要从固件里 dump 出预设动作组数据

## 二、硬件与角度换算

| 项目 | 规格 |
|---|---|
| 主控 | ESP32-S3（以控制器实物为准，三款差异见 §3.1） |
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

### 3.1 三款控制器：命令完全一样，只有 DTR/RTS 不同

松甲机器人 KM1 有三款控制器在流通。**三者串口指令 100% 兼容**：协议前缀、零填充格式、返回数据、角度换算全部一致，同一份控制代码可以原样跑在三款上。**唯一要改的是开串口时 `dtr` / `rts` 两个布尔值。**

| # | 控制器型号 | 串口芯片 | `dtr` | `rts` | 备注 |
|---|---|---|---|---|---|
| 1 | （待补） | （待补） | （待补） | （待补） | |
| 2 | （待补） | （待补） | （待补） | （待补） | |
| 3 | （待补） | （待补） | （待补） | （待补） | |

> 表内型号与配置待实测确认；**型号不明时直接用 §3.3 的自动探测**，不必先查表。

配错的两种表现，正好可以反推是哪类问题：

| 表现 | 含义 | 处理 |
|---|---|---|
| 串口只吐 `waiting for download` | 板子被 DTR/RTS 按进了**下载模式**，固件没跑 | 换一组 `dtr`/`rts`，再重新插拔 USB |
| 串口能开、发指令零回应 | 板子被按在**复位**里，或结束符不对 | 先换 `dtr`/`rts`，再查结束符 |

### 3.2 开串口模板

```python
import serial

ser = serial.Serial()
ser.port = 'COM3'          # Windows: 设备管理器里看；Linux: /dev/ttyUSB0 或 /dev/ttyACM0
ser.baudrate = 115200
ser.dtr = False            # ← 三款控制器只有这两个值不同，按 §3.1 或 §3.3 确定
ser.rts = False
ser.timeout = 0.1
ser.open()
```

### 3.3 型号不确定时的自动探测

四种组合依次试，谁能让固件回话就用谁。**要排除掉"下载模式"的假阳性**——那种情况下串口也有输出，但输出的是 `waiting for download`，不是固件回应。

```python
import time
import serial

CANDIDATES = [(False, False), (True, True), (False, True), (True, False)]


def open_arm(port: str, baud: int = 115200):
    """依次尝试四种 DTR/RTS 组合，返回 (串口对象, 命中的组合)"""
    for dtr, rts in CANDIDATES:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.dtr = dtr
        ser.rts = rts
        ser.timeout = 0.05
        try:
            ser.open()
        except serial.SerialException:
            continue

        ser.reset_input_buffer()
        ser.write(b'$DST!\n')          # 探活指令：正常固件会回 #255PDST!
        deadline, got = time.time() + 1.5, b''
        while time.time() < deadline:
            got += ser.read(ser.in_waiting or 1)
            if b'!' in got:
                break

        if got and b'waiting for download' not in got:
            print(f'[OK] {port}  dtr={dtr} rts={rts}  回应={got[:60]!r}')
            return ser, (dtr, rts)

        ser.close()                     # 这组不对：关掉再试下一组

    raise RuntimeError(f'{port} 四种 DTR/RTS 组合均无有效回应，检查端口号/波特率/供电')


if __name__ == '__main__':
    ser, cfg = open_arm('COM3')
    print('把这两个值写进配置:', cfg)
    ser.close()
```

探测到的组合建议写进配置文件缓存（同一台机器下次直接用），省掉每次 3 秒的试探。

### 3.4 常见错误

| 现象 | 原因 | 解决 |
|---|---|---|
| `SerialException: could not open port` | 端口被占用 | 关掉其他串口软件/上一个没退出的脚本 |
| 只输出 `waiting for download` | DTR/RTS 让板子进了下载模式 | 换一组 `dtr`/`rts`，然后**重新插拔 USB** |
| 发指令无响应 | 结束符不对 / `dtr`/`rts` 不对 | 先查是否以 `!` 结尾（批量是 `}`），再跑 §3.3 |
| 端口找不到 | 驱动未装 | 按串口芯片装 CH340 / CP210x 驱动 |

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

    def __init__(self, port: str, baud: int = 115200, dtr: bool = False, rts: bool = False):
        # dtr/rts 是三款控制器唯一的差异，按 §3.1 或 §3.3 的结果传进来
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baud
        self.ser.dtr = dtr
        self.ser.rts = rts
        self.ser.timeout = 0.1
        self.ser.open()
        print(f'[OK] 已连接 {port} @ {baud} (dtr={dtr}, rts={rts})')

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

除端口名与驱动权限外，**其余代码完全一致**：协议、换算不变，`dtr`/`rts` 也不随系统变——它只随控制器型号变（§3.1）。

## 九、故障排查

| 症状 | 排查顺序 |
|---|---|
| **舵机不动** | ① 是否先发了 `$DST!` ② PWM 是否在 500~2500 ③ 索引是否 0~5 ④ `time` 是否 ≥300ms |
| **乱码 / 无响应** | ① 波特率是否 115200 ② 结束符是否 `!`/`}`/`>` ③ 连上后先发 `$RST!` 重启 |
| **串口打不开** | 列端口确认设备在：`for p in serial.tools.list_ports.comports(): print(p.device, p.description)` |
| **进下载模式** | 日志出现 `ESP-ROM:esp32s3... waiting for download` → 换一组 `dtr`/`rts`（§3.1，或直接跑 §3.3 探测）+ 重新插拔 USB |
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

- **换机先定 `dtr`/`rts`**：三款控制器只有这一处差异，代码别为型号写分支，把两个值做成配置项/探测结果即可
- **新写控制脚本，入口第一件事是 `stop()`**，否则你会以为是代码不生效
- 封装 `send()` 时**三种结束符都要放过**（`!` / `}` / `>`），只判 `!` 会把 `{...}` 拼坏
- 判定完成认 `@GroupDone!`，不要靠 `sleep(2)` 猜（组时长从几百毫秒到十几秒都有）
- 调试时把 `[TX]` 打印出来，对照协议表肉眼核一遍零填充位数
- 硬件类测试**不要手算期望值**，用 `angle_to_pwm()` 反算后打印核对
- 串口对象用完必须 `close()`，否则下次运行报"端口被占用"
