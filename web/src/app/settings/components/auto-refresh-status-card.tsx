"use client";

import { Activity, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fetchAccountAutoRefreshStatus, type AccountAutoRefreshStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

function formatDateTime(value?: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatDuration(value?: number | null) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) {
    return "-";
  }
  if (ms < 1000) {
    return `${ms} ms`;
  }
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatInterval(value?: number | null) {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "-";
  }
  if (seconds % 3600 === 0) {
    return `${seconds / 3600} 小时`;
  }
  if (seconds % 60 === 0) {
    return `${seconds / 60} 分钟`;
  }
  return `${seconds} 秒`;
}

function statusMeta(status?: string, running?: boolean) {
  if (running || status === "running") {
    return { label: "运行中", variant: "info" as const };
  }
  if (status === "success") {
    return { label: "成功", variant: "success" as const };
  }
  if (status === "partial_error") {
    return { label: "部分失败", variant: "warning" as const };
  }
  if (status === "error") {
    return { label: "失败", variant: "danger" as const };
  }
  if (status === "interrupted") {
    return { label: "已中断", variant: "warning" as const };
  }
  return { label: "未运行", variant: "outline" as const };
}

function StatItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-stone-950">{value}</div>
    </div>
  );
}

export function AutoRefreshStatusCard() {
  const [status, setStatus] = useState<AccountAutoRefreshStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = async (silent = false) => {
    if (silent) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    try {
      const data = await fetchAccountAutoRefreshStatus();
      setStatus(data.status);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取失败");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    void loadStatus();
    const timer = window.setInterval(() => {
      void loadStatus(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const meta = statusMeta(status?.last_status, status?.running);
  const hasError = Boolean(status?.last_error || error);

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white">
              {status?.running ? <LoaderCircle className="size-5 animate-spin" /> : <Activity className="size-5" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-stone-950">自动刷新状态</h2>
                <Badge variant={meta.variant}>{meta.label}</Badge>
              </div>
              <div className="mt-1 text-xs text-stone-500">间隔 {formatInterval(status?.interval_seconds)}</div>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
            onClick={() => void loadStatus(true)}
            disabled={isRefreshing}
          >
            <RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            刷新状态
          </Button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <LoaderCircle className="size-5 animate-spin text-stone-400" />
          </div>
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-4">
              <StatItem label="上次开始" value={formatDateTime(status?.last_started_at)} />
              <StatItem label="上次完成" value={formatDateTime(status?.last_finished_at)} />
              <StatItem label="下次预计" value={formatDateTime(status?.next_run_at)} />
              <StatItem label="耗时" value={formatDuration(status?.last_duration_ms)} />
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <StatItem label="账号总数" value={status?.last_total ?? 0} />
              <StatItem label="刷新成功" value={status?.last_refreshed ?? 0} />
              <StatItem label="刷新错误" value={status?.last_error_count ?? 0} />
              <StatItem label="触发恢复" value={status?.last_relogined ?? 0} />
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <StatItem label="Token 保活数" value={status?.last_keepalive_total ?? 0} />
              <StatItem label="保活成功" value={status?.last_keepalive_refreshed ?? 0} />
              <StatItem label="保活错误" value={status?.last_keepalive_error_count ?? 0} />
            </div>
            {hasError ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                {status?.last_error || error}
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
