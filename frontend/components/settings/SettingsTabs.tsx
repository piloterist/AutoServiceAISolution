"use client";

import { useState } from "react";

import { SettingsForm } from "@/components/SettingsForm";
import type { AppSettings, AuditLogEntry, OrgDepartment, OrgUser, SlesarkaStatus, Workshop } from "@/lib/backend-api";

import { AuditLogTab } from "./AuditLogTab";
import { DepartmentsTab } from "./DepartmentsTab";
import { SlesarkaStatusesTab } from "./SlesarkaStatusesTab";
import { UsersTab } from "./UsersTab";
import { WorkshopsTab } from "./WorkshopsTab";

type TabKey = "general" | "users" | "departments" | "workshops" | "statuses" | "log";

const TABS: { key: TabKey; label: string }[] = [
  { key: "general", label: "Общие" },
  { key: "users", label: "Пользователи" },
  { key: "departments", label: "Подразделения" },
  { key: "workshops", label: "Цеха" },
  { key: "statuses", label: "Статусы слесарки" },
  { key: "log", label: "Логи" },
];

export function SettingsTabs({
  appSettings,
  repairTypes,
  departments,
  workshops,
  users,
  statuses,
  auditLog,
}: {
  appSettings: AppSettings;
  repairTypes: string[];
  departments: OrgDepartment[];
  workshops: Workshop[];
  users: OrgUser[];
  statuses: SlesarkaStatus[];
  auditLog: AuditLogEntry[];
}) {
  const [tab, setTab] = useState<TabKey>("general");

  return (
    <div>
      <div className="admin-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={t.key === tab ? "admin-tab admin-tab--on" : "admin-tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "general" && <SettingsForm initialSettings={appSettings} repairTypes={repairTypes} />}
      {tab === "users" && <UsersTab initialUsers={users} departments={departments} workshops={workshops} />}
      {tab === "departments" && <DepartmentsTab initialDepartments={departments} />}
      {tab === "workshops" && <WorkshopsTab initialWorkshops={workshops} departments={departments} />}
      {tab === "statuses" && <SlesarkaStatusesTab initialStatuses={statuses} />}
      {tab === "log" && <AuditLogTab initialEntries={auditLog} />}
    </div>
  );
}
