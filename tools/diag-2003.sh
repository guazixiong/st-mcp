#!/bin/sh
# 诊断：建库成功但端口 2003 没起来（oscar -o normal 起库失败 / 超时）
# 用法：sh diag-2003.sh [库名]      默认 OSRDB
#       需要 root；全程只读，不改任何文件、不启动任何进程。
# 输出是一整块纯文本，把整块发回来即可。
set -u

DB=${1:-OSRDB}
PREFIX=${ST_INSTALL_PREFIX:-/opt/ShenTong}
PORT=${ST_PORT:-2003}
OSCAR=$PREFIX/bin/oscar
RUNLOG=/tmp/st-2003-diag-$DB.log

{
    echo "=============== 采集开始 $(date '+%F %T') ==============="

    echo "--- [1] 机器与内核 ---"
    uname -a
    printf 'arch=%s  cpus=%s\n' "$(uname -m)" "$(nproc 2>/dev/null || echo '?')"
    grep PRETTY /etc/os-release 2>/dev/null
    uptime 2>/dev/null

    echo "--- [2] 内存（默认缓冲池≈3.2GB，内存不足会被内核杀掉）---"
    free -m 2>/dev/null || awk '/MemTotal|MemAvailable/ {printf "%s %d MB\n", $1, $2/1024}' /proc/meminfo
    swap 2>/dev/null || swapon -s 2>/dev/null || echo "(swapon 不可用)"

    echo "--- [3] SELinux（强制模式会拦住引擎启动）---"
    command -v getenforce >/dev/null 2>&1 && getenforce || echo "(无 getenforce，视为未启用)"
    command -v ausearch >/dev/null 2>&1 && \
        ausearch -m avc -ts recent 2>/dev/null | tail -8 && echo "(上面是最近的 AVC 拒绝，空则无)"

    echo "--- [4] 交付包与库文件 ---"
    ls -ld "$PREFIX" 2>&1
    ls -l "$OSCAR" 2>&1
    ls -l "$PREFIX/odbs/$DB"/*.dbf 2>&1 | head -10
    ls -l "$PREFIX/admin/$DB.conf" "$PREFIX/admin/$DB.db" 2>&1

    echo "--- [5] 依赖是否齐（应为空）---"
    ldd "$OSCAR" 2>/dev/null | awk '$2 == "=>" && $3 == "not" && $4 == "found" { print "MISSING " $1 }'
    ls -l "$PREFIX/bin/so" 2>/dev/null | grep -E "tirpc|krb5|com_err|keyutils"

    echo "--- [6] 生效的缓冲池参数（同名键最后一行生效）---"
    grep -n 'BUF_DATA_BUFFER_PAGES\|SORT_MEM\|THREADPOOL_MAX_THREADS' "$PREFIX/admin/$DB.conf" 2>&1 | tail -12

    echo "--- [7] oscar 进程 ---"
    ps -ef 2>/dev/null | grep -i "[o]scar" || echo "(没有任何 oscar 进程)"
    if [ -f "$PREFIX/admin/$DB.db" ]; then
        printf 'admin/%s.db 内容：%s\n' "$DB" "$(cat "$PREFIX/admin/$DB.db" 2>&1)"
    fi

    echo "--- [8] 端口 ---"
    (ss -lntp 2>/dev/null || netstat -lntp 2>/dev/null) | grep -E ":$PORT|:8100" || echo "($PORT 与 8100 都没人监听)"

    echo "--- [9] 内核有没有 OOM 杀过 oscar ---"
    dmesg 2>/dev/null | grep -iE "out of memory|oom-kill|killed process" | tail -10 || true
    command -v journalctl >/dev/null 2>&1 && journalctl -k --no-pager -p err 2>/dev/null | tail -10

    echo "--- [10] 引擎自己的日志（最关键）---"
    ls -lt "$PREFIX/log/$DB" 2>/dev/null | head -8
    # 只看最新的 elog_*（agent_log.txt 之类的不含起库失败原因）
    ELOG=$(ls -t "$PREFIX"/log/"$DB"/elog_* 2>/dev/null | head -1)
    if [ -n "$ELOG" ]; then
        echo "  >>> $ELOG 里所有 ERROR / FATAL / 中文告警行"
        grep -nE "ERROR|FATAL|错误|失败|拒绝|cannot|denied" "$ELOG" 2>/dev/null | tail -25 | sed 's/^/  /'
        echo "  >>> $ELOG 最后 40 行"
        tail -n 40 "$ELOG" 2>&1 | sed 's/^/  /'
    else
        echo "  ($PREFIX/log/$DB/ 下没有 elog_*，列出目录里最近改动的文件)"
        find "$PREFIX/log" -maxdepth 2 -type f -mmin -120 2>/dev/null | head -10
    fi

    echo "--- [11] 服务注册与启动脚本 ---"
    ls -l "/etc/init.d/oscardb_${DB}d" 2>&1
    ls -l "$PREFIX/bin/dbcontrol" 2>&1
    chkconfig --list 2>/dev/null | grep -i oscar || echo "(chkconfig 里没有 oscar 条目)"

    echo "--- [12] 许可（介质自带的是 90 天试用）---"
    ls -l "$PREFIX/license" 2>&1 | head -5
    date '+今天：%F'
    grep -ho 'usedays=[0-9]*\|invalidday=[0-9]*' "$PREFIX"/log/"$DB"/elog_* "$PREFIX"/admin/* 2>/dev/null | sort -u | head -5

    echo "--- [13] 口令与连通侧（容器还没起，这里只查库）---"
    (command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}} {{.Status}}' 2>&1 | head -5) || echo "(无 docker)"

    echo "=============== 采集结束 ==============="
    echo
    echo "下一步（手动起库，前台运行 90 秒，能把真实报错直接打出来）："
    echo "    su - $(stat -c %U "$PREFIX" 2>/dev/null || echo oscar) -c \"env SZ_OSCAR_HOME=$PREFIX LD_LIBRARY_PATH=$PREFIX/bin timeout 90 $OSCAR -o normal -d $DB\" 2>&1 | tail -40"
    echo "（Ctrl+C 可提前结束；这条命令只读库文件用于起实例，不改配置）"
} 2>&1 | tee "$RUNLOG"

echo
echo "[diag-2003] 以上内容的副本已写到 $RUNLOG，可直接把整屏贴回来。"
