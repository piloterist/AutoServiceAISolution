"use client";

import { useState } from "react";

import { SettingsForm } from "@/components/SettingsForm";
import type {
  AppSettings,
  AuditLogEntry,
  Employee,
  LeadsSettings,
  OrgDepartment,
  OrgUser,
  PhoneSource,
  RoleTabVisibility,
  SlesarkaStatus,
  TelephonySettings,
  Workshop,
  WorkshopPhoneMapping,
  WorkshopSourceDepartment,
} from "@/lib/backend-api";

import { AuditLogTab } from "./AuditLogTab";
import { CostItemsTab } from "./CostItemsTab";
import { EmployeesTab } from "./EmployeesTab";
import { LeadsTab } from "./LeadsTab";
import { OrgStructureTab } from "./OrgStructureTab";
import { RoleTabVisibilityCard } from "./RoleTabVisibilityCard";
import { TelephonyTab } from "./TelephonyTab";
import { UsersTab } from "./UsersTab";

type TabKey =
  | "general"
  | "users"
  | "org-structure"
  | "employees"
  | "telephony"
  | "finance"
  | "leads"
  | "log";

const TABS: { key: TabKey; label: string }[] = [
  { key: "general", label: "Общие" },
  { key: "users", label: "Пользователи" },
  { key: "org-structure", label: "Орг. структура" },
  { key: "employees", label: "Сотрудники" },
  { key: "telephony", label: "IP-телефония" },
  { key: "finance", label: "Финансы" },
  { key: "leads", label: "Заявки" },
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
  workshopPhoneMappings,
  leadsSettings,
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
  workshopPhoneMappings: WorkshopPhoneMapping[];
  leadsSettings: LeadsSettings;
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
      {tab === "org-structure" && (
        <OrgStructureTab
          departments={departments}
          workshops={workshops}
          sourceDepartments={sourceDepartments}
          unmappedSourceDepartments={unmappedSourceDepartments}
          statuses={statuses}
        />
      )}
      {tab === "employees" && (
        <EmployeesTab initialEmployees={employees} departments={departments} workshops={workshops} />
      )}
      {tab === "telephony" && (
        <TelephonyTab
          initialSettings={telephonySettings}
          initialSources={phoneSources}
          initialWorkshopPhones={workshopPhoneMappings}
          workshops={workshops}
        />
      )}
      {tab === "finance" && <CostItemsTab />}
      {tab === "leads" && <LeadsTab initialSettings={leadsSettings} />}
      {tab === "log" && <AuditLogTab initialEntries={auditLog} />}
    </div>
  );
}
