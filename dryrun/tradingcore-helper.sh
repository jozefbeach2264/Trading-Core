#!/bin/bash
# tradingcore — one-command control of the dry run (model server + bot + data collector).
#   tradingcore start        start model server, wait for it, start bot, start collector timer
#   tradingcore stop         stop bot + collector timer + model server (frees the GPU for other work)
#   tradingcore pause        stop bot + collector, keep the model server (quick resume)
#   tradingcore resume       start bot + collector again
#   tradingcore status       units, /stats, last sample
#   tradingcore report       summarise collected samples
#   tradingcore watch        open the live dashboard (http://127.0.0.1:8001/)
#   tradingcore tail         live cycle stream in this terminal (Ctrl-C to leave)
set -u
MODEL=llama-server@trading.service; BOT=tradingcore.service; TIMER=tradingcore-collector.timer
wait_health() { for _ in $(seq 1 180); do curl -s -m 2 "$1" 2>/dev/null | grep -q "$2" && return 0; sleep 1; done; return 1; }
case "${1:-status}" in
  start)
    systemctl --user start "$MODEL" && wait_health http://127.0.0.1:8081/health '"ok"' || { echo "model server not healthy" >&2; exit 1; }
    systemctl --user start "$BOT" && wait_health http://127.0.0.1:8000/status '"ok"' || { echo "bot not healthy" >&2; exit 1; }
    systemctl --user start "$TIMER"; python3 "$HOME/trading_core_project/dryrun/collect.py" >/dev/null
    echo "running: $(systemctl --user is-active $MODEL) / $(systemctl --user is-active $BOT) / collector $(systemctl --user is-active $TIMER)";;
  stop)    systemctl --user stop "$BOT" "$TIMER" "$MODEL"; echo "stopped (GPU free: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader))";;
  pause)   systemctl --user stop "$BOT" "$TIMER"; echo "paused (model server still resident)";;
  resume)  systemctl --user start "$BOT" "$TIMER"; wait_health http://127.0.0.1:8000/status '"ok"' && echo "resumed";;
  status)  for u in "$MODEL" "$BOT" "$TIMER"; do printf '%-32s %s\n' "$u" "$(systemctl --user is-active "$u")"; done
           curl -s -m 3 http://127.0.0.1:8000/stats | python3 -m json.tool 2>/dev/null | head -40
           tail -1 "$HOME/trading_core_project/dryrun/samples.jsonl" 2>/dev/null | cut -c1-300;;
  report)  python3 "$HOME/trading_core_project/dryrun/report.py";;
  trades)  python3 "$HOME/trading_core_project/dryrun/trade_review.py";;
  watch)   systemctl --user is-active --quiet tradingcore-dashboard.service || systemctl --user start tradingcore-dashboard.service
           echo "dashboard: http://127.0.0.1:8001/"; xdg-open http://127.0.0.1:8001/ >/dev/null 2>&1 || true;;
  tail)    python3 "$HOME/trading_core_project/dryrun/dashboard.py" --tail;;
  *) echo "usage: tradingcore start|stop|pause|resume|status|report|watch|tail" >&2; exit 2;;
esac
