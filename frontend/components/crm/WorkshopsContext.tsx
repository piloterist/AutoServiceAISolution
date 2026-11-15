"use client";

import { createContext, useContext } from "react";

import type { Employee, Workshop } from "@/lib/backend-api";

/** The цеха of the CRM page - for the board's filter and the "На контроль" dialog of a call, which
 * sits several components below TelephonyTabs. */
const WorkshopsContext = createContext<Workshop[]>([]);

export const WorkshopsProvider = WorkshopsContext.Provider;

export function useWorkshops(): Workshop[] {
  return useContext(WorkshopsContext);
}

/** The employees of the CRM page (for the board's "Сотрудник" filter and the "На контроль" dialog)
 * and the one the logged-in user is linked to (preselected in the dialog). */
type EmployeesValue = { employees: Employee[]; currentEmployeeId: string | null };

const EmployeesContext = createContext<EmployeesValue>({ employees: [], currentEmployeeId: null });

export const EmployeesProvider = EmployeesContext.Provider;

export function useEmployees(): EmployeesValue {
  return useContext(EmployeesContext);
}

/** The employees of one цех (sorted by name); every employee if no цех is chosen. */
export function employeesOfWorkshop(employees: Employee[], workshopId: string | null): Employee[] {
  return employees
    .filter((employee) => !workshopId || employee.workshop_id === workshopId)
    .sort((a, b) => a.full_name.localeCompare(b.full_name, "ru"));
}

export function workshopLabel(workshop: Workshop): string {
  return `${workshop.department_name} — ${workshop.workshop_type}`;
}
