"use client";

import { useState } from "react";

import { SettingsForm } from "@/components/SettingsForm";
import type {
  AppSettings,
  AuditLogEntry,
  Employee,
  OrgDepartment,
  OrgUser,
  PhoneSource,
  RoleTabVisibility,
  SlesarkaStatus,
  TelephonySettings,
  Workshop,
  WorkshopSourceDepartment,
} from "@/lib/backend-api";

import { AuditLogTab } from "./AuditLogTab";
import { DepartmentsTab } from "./DepartmentsTab";
import { EmployeesTab } from "./EmployeesTab";
import { RoleTabVisibilityCard } from "./RoleTabVisibilityCard";
import { SlesarkaStatusesTab } from "./SlesarkaStatusesTab";
import { TelephonyTab } from "./TelephonyTab";
import { UsersTab } from "./UsersTab";
import { WorkshopSourceDepartmentsTab } from "./WorkshopSourceDepartmentsTab";
import { WorkshopsTab } from "./WorkshopsTab";

type TabKey =
  | "general"
  | "users"
  | "departments"
  | "workshops"
  | "source-departments"
  | "statuses"
  | "employees"
  | "telephony"
  | "log";

const TABS: { key: TabKey; label: string }[] = [
  { key: "general", label: "Общие" },
  { key: "users", label: "Пользователи" },
  { key: "departments", label: "Подразделения" },
  { key: "workshops", label: "Цеха" },
  { key: "source-departments", label: "Соответствие 1С" },
  { key: "statuses", label: "Статусы слесарки" },
  { key: "employees", label: "Сотрудники" },
  { key: "telephony", label: "IP-телефония" },
  { key: "log", label: "Логи" },
];

export function SettingsTabs({
  appSettings,
  repairTypes,
  departments,
  workshops,
  sourceDepartments,
  unmappedSourceDepartments,
  users,
  statuses,
  employees,
  roleTabVisibility,
  telephonySettings,
  phoneSources,
  auditLog,
}: {
  appSettings: AppSettings;
  repairTypes: string[];
  departments: OrgDepartment[];
  workshops: Workshop[];
  sourceDepartments: WorkshopSourceDepartment[];
  unmappedSourceDepartments: string[];
  users: OrgUser[];
  statuses: SlesarkaStatus[];
  employees: Employee[];
  roleTabVisibility: RoleTabVisibility[];
  telephonySettings: TelephonySettings;
  phoneSources: PhoneSource[];
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
      {tab === "users" && (
        <>
          <UsersTab initialUsers={users} departments={departments} workshops={workshops} />
          <RoleTabVisibilityCard initialRows={roleTabVisibility} />
        </>
      )}
      {tab === "departments" && <DepartmentsTab initialDepartments={departments} />}
      {tab === "workshops" && <WorkshopsTab initialWorkshops={workshops} departments={departments} />}
      {tab === "source-departments" && (
        <WorkshopSourceDepartmentsTab
          initialRows={sourceDepartments}
          initialUnmapped={unmappedSourceDepartments}
          workshops={workshops}
        />
      )}
      {tab === "statuses" && <SlesarkaStatusesTab initialStatuses={statuses} />}
      {tab === "employees" && (
        <EmployeesTab initialEmployees={employees} departments={departments} workshops={workshops} />
      )}
      {tab === "telephony" && (
        <TelephonyTab initialSettings={telephonySettings} initialSources={phoneSources} />
      )}
      {tab === "log" && <AuditLogTab initialEntries={auditLog} />}
    </div>
  );
}
