"use client";

import { useState } from "react";

import { DateInput } from "@/components/DateInput";
import { MultiSelectDropdown } from "@/components/MultiSelectDropdown";
import type { AppSettings, AutoMatchResult, OrderExclusionMode } from "@/lib/backend-api";
import { invalidateWorkOrdersCache } from "@/lib/work-orders-cache";

type SaveState = "idle" | "saving" | "saved" | "error";

export function SettingsForm({
  initialSettings,
  repairTypes,
}: {
  initialSettings: AppSettings;
  /** Distinct ЗаказНаряд.ВидРемонта values actually present in imported
   * work orders (see getRepairTypes) - never a hardcoded list. */
  repairTypes: string[];
}) {
  const [insuranceRepairType, setInsuranceRepairType] = useState(
    initialSettings.insurance_repair_type ?? "",
  );
  const [excludeInternal, setExcludeInternal] = useState(
    initialSettings.exclude_internal_insurance,
  );
  // "Специфика PanMotors" - a separate feature from the two above (which
  // drive the older insurance-reporting exclusion): what the dashboard-style
  // figures leave out - nothing / the internal orders (WorkOrder.is_internal, a
  // car/VIN-and-org/payer-based detection, see backend services/
  // internal_order_rules.py) / the insurance ones (see order_exclusion.py).
  const [orderExclusionMode, setOrderExclusionMode] = useState<OrderExclusionMode>(
    initialSettings.order_exclusion_mode,
  );
  const [receivablesMaxAgeDays, setReceivablesMaxAgeDays] = useState(
    initialSettings.receivables_max_age_days ? String(initialSettings.receivables_max_age_days) : "",
  );
  const [hideInternalOrders, setHideInternalOrders] = useState(
    initialSettings.hide_internal_orders,
  );
  // Which ВидРемонта values count as warranty work - multi-select, feeds
  // only the Финансы -> Дебиторская задолженность aging table's own
  // Все/Страховые/Текущие filter (see ReceivablesAgingView.tsx).
  const [warrantyRepairTypes, setWarrantyRepairTypes] = useState<string[]>(
    initialSettings.warranty_repair_types ?? [],
  );
  const toggleWarrantyRepairType = (type: string) => {
    setWarrantyRepairTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };
  // "Виртуальные": same list, same kind of choice - never revenue either.
  const [virtualRepairTypes, setVirtualRepairTypes] = useState<string[]>(
    initialSettings.virtual_repair_types ?? [],
  );
  const toggleVirtualRepairType = (type: string) => {
    setVirtualRepairTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };
  // Planner's "Получить ЗН" live 5Systems plate lookup - a runtime switch
  // staff can flip here without a deploy. Still requires the backend's own
  // ENABLE_FIVESYSTEMS_LOOKUP env var (credentials configured) - this
  // checkbox alone can't turn the feature on if that isn't set too, see
  // backend/app/models/app_settings.py.
  const [fivesystemsApiEnabled, setFivesystemsApiEnabled] = useState(
    initialSettings.fivesystems_api_enabled,
  );
  // Every non-Admin session still open at/after this time (Moscow) gets
  // force-logged-out - see lib/auth.ts's nextDailyBoundary and
  // middleware.ts. Baked into the session cookie at login, so a change
  // here takes effect for logins AFTER the save, same staleness tradeoff
  // allowedTabs already has (no mid-session push, no server-side session
  // store to revoke from - see lib/auth.ts's module comment).
  const [dailyLogoutTime, setDailyLogoutTime] = useState(initialSettings.daily_logout_time);
  // Auto-links an unlinked Planner record (WorkshopJob/BodyCar with no ЗН
  // yet) to a work order imported shortly afterward, matched by phone or
  // VIN - see backend services/planner_service.auto_match_planner_records.
  const [plannerAutoMatchEnabled, setPlannerAutoMatchEnabled] = useState(
    initialSettings.planner_auto_match_enabled,
  );
  const [plannerAutoMatchIntervalMinutes, setPlannerAutoMatchIntervalMinutes] = useState(
    String(initialSettings.planner_auto_match_interval_minutes),
  );
  const [plannerSearchExcludeClosedOrders, setPlannerSearchExcludeClosedOrders] = useState(
    initialSettings.planner_search_exclude_closed_orders,
  );
  // Касса: the locked period (both inclusive) - empty = nothing locked.
  const [cashLockFrom, setCashLockFrom] = useState(initialSettings.cash_lock_from ?? "");
  const [cashLockTo, setCashLockTo] = useState(initialSettings.cash_lock_to ?? "");
  // Контроль заявок на ремонт (backend services/request_control_service.py).
  const [requestControlEnabled, setRequestControlEnabled] = useState(initialSettings.request_control_enabled);
  const [requestFirstCallDays, setRequestFirstCallDays] = useState(String(initialSettings.request_first_call_days));
  const [requestSecondCallDays, setRequestSecondCallDays] = useState(String(initialSettings.request_second_call_days));
  const [requestMinTalkSec, setRequestMinTalkSec] = useState(String(initialSettings.request_min_talk_sec));
  const [requestPopupEnabled, setRequestPopupEnabled] = useState(initialSettings.request_popup_enabled);
  const [requestPopupIntervalMinutes, setRequestPopupIntervalMinutes] = useState(
    String(initialSettings.request_popup_interval_minutes),
  );
  const [requestAutoDisqualifyDays, setRequestAutoDisqualifyDays] = useState(
    String(initialSettings.request_auto_disqualify_days),
  );
  // Доска задач CRM (backend services/crm_task_service.py): сроки окраски карточек «На контроле».
  const [crmTaskWarnDays, setCrmTaskWarnDays] = useState(String(initialSettings.crm_task_warn_days));
  const [crmTaskOverdueDays, setCrmTaskOverdueDays] = useState(String(initialSettings.crm_task_overdue_days));
  const [crmTaskArchiveDays, setCrmTaskArchiveDays] = useState(String(initialSettings.crm_task_archive_days));
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [autoMatchState, setAutoMatchState] = useState<"idle" | "running" | "done" | "error">(
    "idle",
  );
  const [autoMatchMessage, setAutoMatchMessage] = useState<string | null>(null);

  const handleSave = async () => {
    setSaveState("saving");
    try {
      const res = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          insurance_repair_type: insuranceRepairType || null,
          exclude_internal_insurance: excludeInternal,
          order_exclusion_mode: orderExclusionMode,
          receivables_max_age_days: Number(receivablesMaxAgeDays) > 0 ? Number(receivablesMaxAgeDays) : null,
          hide_internal_orders: hideInternalOrders,
          warranty_repair_types: warrantyRepairTypes,
          virtual_repair_types: virtualRepairTypes,
          fivesystems_api_enabled: fivesystemsApiEnabled,
          daily_logout_time: dailyLogoutTime,
          planner_auto_match_enabled: plannerAutoMatchEnabled,
          planner_auto_match_interval_minutes: Number(plannerAutoMatchIntervalMinutes) || 180,
          planner_search_exclude_closed_orders: plannerSearchExcludeClosedOrders,
          cash_lock_from: cashLockFrom || null,
          cash_lock_to: cashLockTo || null,
          request_control_enabled: requestControlEnabled,
          request_first_call_days: Number(requestFirstCallDays) || 3,
          request_second_call_days: Number(requestSecondCallDays) || 7,
          request_min_talk_sec: Number(requestMinTalkSec) || 20,
          request_popup_enabled: requestPopupEnabled,
          request_popup_interval_minutes: Number(requestPopupIntervalMinutes) || 30,
          request_auto_disqualify_days: Number(requestAutoDisqualifyDays) || 30,
          crm_task_warn_days: Number(crmTaskWarnDays) || 1,
          crm_task_overdue_days: Number(crmTaskOverdueDays) || 3,
          crm_task_archive_days: Number(crmTaskArchiveDays) || 30,
        } satisfies AppSettings),
      });
      if (!res.ok) throw new Error(await res.text());
      // The cached work orders list carries the repair requests' overdue marks (request_issue),
      // which depend on these settings - drop it so the list is refetched with the new ones.
      invalidateWorkOrdersCache();
      setSaveState("saved");
    } catch {
      setSaveState("error");
    } finally {
      setTimeout(() => setSaveState("idle"), 2000);
    }
  };

  const handleAutoMatchNow = async () => {
    setAutoMatchState("running");
    setAutoMatchMessage(null);
    try {
      const res = await fetch("/api/planner/auto-match", { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const result = (await res.json()) as AutoMatchResult;
      setAutoMatchState("done");
      setAutoMatchMessage(
        `Проверено записей: ${result.processed}, привязано: ${result.matched}`,
      );
    } catch (err) {
      setAutoMatchState("error");
      setAutoMatchMessage(err instanceof Error ? err.message : "Не удалось выполнить");
    }
  };

  const saveLabel =
    saveState === "saving"
      ? "Сохранение…"
      : saveState === "saved"
        ? "Сохранено ✓"
        : saveState === "error"
          ? "Не удалось сохранить"
          : "Сохранить";

  return (
    <div className="card settings-general">
      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Страховые</h3>

        <div className="settings-field">
          <label htmlFor="insurance-repair-type">Вид ремонта для страховых</label>
          <select
            id="insurance-repair-type"
            value={insuranceRepairType}
            onChange={(event) => setInsuranceRepairType(event.target.value)}
          >
            <option value="">Не выбрано</option>
            {repairTypes.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={excludeInternal}
            onChange={(event) => setExcludeInternal(event.target.checked)}
          />
          Исключить внутренние по страховым
        </label>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Специфика PanMotors</h3>

        <div className="settings-field">
          <label htmlFor="order-exclusion-mode">Исключить</label>
          <select
            id="order-exclusion-mode"
            value={orderExclusionMode}
            onChange={(event) => setOrderExclusionMode(event.target.value as OrderExclusionMode)}
          >
            <option value="none">Без исключений</option>
            <option value="internal">Внутренние</option>
            <option value="external">Внешние</option>
          </select>
          <p className="settings-description">
            Влияет на выручку, оплаты, дебиторскую задолженность и бюджеты (дашборд, Финансы,
            Бюджеты). «Без исключений» — учитываются все заказ-наряды; «Внутренние» — не учитываются
            внутренние заказ-наряды; «Внешние» — не учитываются заказ-наряды с видом ремонта «Вид
            ремонта для страховых» (выбирается выше; пока он не выбран, ничего не исключается). На
            список заказ-нарядов настройка не влияет.
          </p>
        </div>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={hideInternalOrders}
            onChange={(event) => setHideInternalOrders(event.target.checked)}
          />
          Скрыть внутренние <span className="settings-hint">(в разработке)</span>
        </label>

        <div className="settings-field">
          <span>Гарантийные (виды ремонта)</span>
          <MultiSelectDropdown
            label="Виды ремонта"
            options={repairTypes}
            selected={warrantyRepairTypes}
            onToggle={toggleWarrantyRepairType}
            onClear={() => setWarrantyRepairTypes([])}
            emptyMessage="Нет данных по видам ремонта"
          />
          <p className="settings-description">
            Не учитываются в выручке на всех вкладках (Аналитика, ESP, Финансы) и в дебиторской
            задолженности; фильтр «Текущие/Страховые» на Финансы → Дебиторская задолженность тоже
            их учитывает.
          </p>
        </div>

        <div className="settings-field">
          <span>Виртуальные (виды ремонта)</span>
          <MultiSelectDropdown
            label="Виды ремонта"
            options={repairTypes}
            selected={virtualRepairTypes}
            onToggle={toggleVirtualRepairType}
            onClear={() => setVirtualRepairTypes([])}
            emptyMessage="Нет данных по видам ремонта"
          />
          <p className="settings-description">
            Не попадают в выручку ни на одной вкладке (Аналитика, ESP, Финансы).
          </p>
        </div>

        <div className="settings-field">
          <label htmlFor="receivables-max-age">Не показывать дебиторку старше (дней)</label>
          <input
            id="receivables-max-age"
            type="number"
            min={1}
            placeholder="без ограничения"
            value={receivablesMaxAgeDays}
            onChange={(event) => setReceivablesMaxAgeDays(event.target.value)}
          />
          <p className="settings-description">
            Долг, просроченный больше чем на указанное число дней (от даты последнего счёта на
            оплату, а если счёта нет — от даты закрытия), не показывается ни в Финансы →
            Дебиторская задолженность, ни на плашке ДЗ во вкладке ESP. Пусто — показывать всё.
          </p>
        </div>

        <p className="settings-description">
          <strong>Правила определения внутренних.</strong> Заказ-наряд считается «внутренним», если
          одновременно выполнены два условия: (1) на этот же автомобиль (по VIN) есть хотя бы один
          «внешний» заказ-наряд с видом ремонта «Страховой»; и (2) организация и плательщик
          заказ-наряда проходят правило, заданное для этой организации (для одних организаций
          внутренний заказ-наряд допускается всегда, для других — только если плательщик не
          физическое лицо). Заказ-наряды без распознанного VIN никогда не считаются внутренними.
          Режим «Внутренние» в настройке «Исключить» выше исключает такие заказ-наряды из
          показателей — как будто их не существует; на список заказ-нарядов это не влияет, там есть
          отдельный фильтр «Внутренний».
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Сессия</h3>

        <div className="settings-field">
          <label htmlFor="daily-logout-time">Автовыход в</label>
          <input
            id="daily-logout-time"
            type="time"
            value={dailyLogoutTime}
            onChange={(event) => setDailyLogoutTime(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Ежедневно в указанное время (по Москве) все пользователи, кроме Админа, автоматически
          разлогиниваются при следующем действии в системе. Изменение применяется к новым входам —
          уже открытые сессии выйдут по старому времени, пока не перелогинятся.
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Планировщик</h3>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={plannerAutoMatchEnabled}
            onChange={(event) => setPlannerAutoMatchEnabled(event.target.checked)}
          />
          Автоматически привязывать ЗН к записям планировщика
        </label>

        <div className="settings-field">
          <label htmlFor="planner-auto-match-interval">Проверять раз в (мин)</label>
          <input
            id="planner-auto-match-interval"
            type="number"
            min={1}
            value={plannerAutoMatchIntervalMinutes}
            onChange={(event) => setPlannerAutoMatchIntervalMinutes(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Если в записи планировщика (Слесарный/Кузовной) ещё не указан заказ-наряд, система ищет
          среди недавно пришедших из 1С ЗН (с даты создания записи и не позже чем через 3 дня
          после) такой же номер телефона или VIN — и если находит, подставляет заказ-наряд, а
          пустые поля «Автомобиль»/«Клиент»/VIN/телефон заполняет из него. Уже заполненные вручную
          поля и уже привязанные к ЗН записи никогда не трогаются.
        </p>

        <button
          type="button"
          className="admin-btn"
          onClick={handleAutoMatchNow}
          disabled={autoMatchState === "running"}
        >
          {autoMatchState === "running" ? "Выполняется…" : "Выполнить сейчас"}
        </button>

        {autoMatchMessage && (
          <p className={autoMatchState === "error" ? "admin-form-error" : "settings-description"}>
            {autoMatchMessage}
          </p>
        )}

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={plannerSearchExcludeClosedOrders}
            onChange={(event) => setPlannerSearchExcludeClosedOrders(event.target.checked)}
          />
          Исключить Закрыт и Выполнен
        </label>

        <p className="settings-description">
          Не показывать в поиске заказ-наряда (по номеру, VIN и т.п.) при создании записи
          планировщика заказ-наряды в статусе «Закрыт» или «Выполнен» — привязывать новую запись к
          уже завершённому заказ-наряду незачем.
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Контроль заявок на ремонт</h3>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={requestControlEnabled}
            onChange={(event) => setRequestControlEnabled(event.target.checked)}
          />
          Включить контроль заявок
        </label>

        <p className="settings-description">
          Заявка на ремонт — документ из 1С, по которому клиент заехал на дефектовку. Пока по ней не
          создан заказ-наряд, клиенту надо дозвониться и поговорить дважды. Сроки считаются от даты
          создания заявки. Просроченные заявки видны в листе «Ошибки», на колокольчике планировщика
          (по цеху пользователя) и подсвечиваются розовым в списке заказ-нарядов. Выключено — ничего
          из этого не показывается.
        </p>

        <div className="settings-field">
          <label htmlFor="request-first-call-days">Первый звонок — в течение (дней)</label>
          <input
            id="request-first-call-days"
            type="number"
            min={1}
            value={requestFirstCallDays}
            onChange={(event) => setRequestFirstCallDays(event.target.value)}
          />
        </div>
        <div className="settings-field">
          <label htmlFor="request-second-call-days">Второй звонок — в течение (дней)</label>
          <input
            id="request-second-call-days"
            type="number"
            min={1}
            value={requestSecondCallDays}
            onChange={(event) => setRequestSecondCallDays(event.target.value)}
          />
        </div>
        <div className="settings-field">
          <label htmlFor="request-min-talk-sec">Разговор считается попыткой от (сек)</label>
          <input
            id="request-min-talk-sec"
            type="number"
            min={1}
            value={requestMinTalkSec}
            onChange={(event) => setRequestMinTalkSec(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Попытка — состоявшийся исходящий разговор с клиентом (звонок на номер из заявки с любой
          линии, не короче указанного времени) или ручная отметка с комментарием. Недозвон попыткой
          не считается: звонить нужно, пока не дозвонятся. Два разговора в один день — одна попытка.
          Дисквалифицировать заявку можно после двух попыток; без них — только роли с правом
          «Дисквалификация заявок без попыток» (Настройки → Пользователи → Права доступа).
        </p>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={requestPopupEnabled}
            onChange={(event) => setRequestPopupEnabled(event.target.checked)}
          />
          Жёлтое напоминание в планировщике
        </label>
        <div className="settings-field">
          <label htmlFor="request-popup-interval">Повторять каждые (мин)</label>
          <input
            id="request-popup-interval"
            type="number"
            min={1}
            value={requestPopupIntervalMinutes}
            onChange={(event) => setRequestPopupIntervalMinutes(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Мастерам-приёмщикам цеха в планировщике показывается окно с восклицательным знаком и списком
          просроченных заявок: при каждом открытии планировщика и затем с указанным периодом, пока
          просроченные есть. Колокольчик со счётчиком остаётся и при выключенном окне.
        </p>

        <div className="settings-field">
          <label htmlFor="request-auto-disqualify">Автодисквалификация заявок старше (дней)</label>
          <input
            id="request-auto-disqualify"
            type="number"
            min={1}
            value={requestAutoDisqualifyDays}
            onChange={(event) => setRequestAutoDisqualifyDays(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Заявка без заказ-наряда старше указанного срока (от даты создания) считается
          дисквалифицированной автоматически и больше не попадает в просрочку.
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Доска задач CRM</h3>

        <div className="settings-field">
          <label htmlFor="crm-task-warn-days">Розовая карточка — на контроле дольше (дней)</label>
          <input
            id="crm-task-warn-days"
            type="number"
            min={1}
            value={crmTaskWarnDays}
            onChange={(event) => setCrmTaskWarnDays(event.target.value)}
          />
        </div>
        <div className="settings-field">
          <label htmlFor="crm-task-overdue-days">Красная карточка — на контроле дольше (дней)</label>
          <input
            id="crm-task-overdue-days"
            type="number"
            min={1}
            value={crmTaskOverdueDays}
            onChange={(event) => setCrmTaskOverdueDays(event.target.value)}
          />
        </div>
        <div className="settings-field">
          <label htmlFor="crm-task-archive-days">Архив — «Отказ» и «Заказ-наряд» старше (дней)</label>
          <input
            id="crm-task-archive-days"
            type="number"
            min={1}
            value={crmTaskArchiveDays}
            onChange={(event) => setCrmTaskArchiveDays(event.target.value)}
          />
        </div>

        <p className="settings-description">
          Телефон попадает на доску кнопкой «На контроль» у звонка. Пока карточка висит в столбце
          «На контроле» дольше первого срока, она розовая, дольше второго — красная; сроки считаются
          от попадания карточки в столбец. Рядом с трубкой в планировщике показывается число карточек
          цеха, дошедших хотя бы до розового срока. Карточки «Отказ» и «Заказ-наряд» старше срока
          архива скрываются с доски; вернуть их можно галкой «Показать архивные».
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Касса</h3>

        <div className="settings-field">
          <label htmlFor="cash-lock-from">Период блокировки: с</label>
          <DateInput id="cash-lock-from" value={cashLockFrom} onChange={setCashLockFrom} ariaLabel="Блокировка кассы с" />
        </div>
        <div className="settings-field">
          <label htmlFor="cash-lock-to">по</label>
          <DateInput id="cash-lock-to" value={cashLockTo} onChange={setCashLockTo} ariaLabel="Блокировка кассы по" />
        </div>

        <p className="settings-description">
          В указанный период (обе даты включительно) нельзя добавлять, изменять и удалять записи кассы —
          у всех цехов сразу. Чтобы закрыть уже сверенные дни, укажите их здесь; по мере закрытия новых
          дней двигайте «по» вперёд. Оставьте поля пустыми, чтобы ничего не блокировать.
        </p>
      </div>

      <div className="settings-subgroup">
        <h3 className="settings-subgroup-title">Интеграции</h3>

        <label className="settings-checkbox">
          <input
            type="checkbox"
            checked={fivesystemsApiEnabled}
            onChange={(event) => setFivesystemsApiEnabled(event.target.checked)}
          />
          Включить API
        </label>

        <p className="settings-description">
          Кнопка «Получить ЗН» в Планировщике — поиск ещё не выгруженного из 1С заказ-наряда
          напрямую по гос.номеру через API 5Systems. Если выключить — кнопка в Планировщике
          станет недоступна, независимо от того, введён гос.номер или нет.
        </p>
      </div>

      <div className="settings-subgroup settings-subgroup--actions">
        <button
          type="button"
          className="settings-save"
          onClick={handleSave}
          disabled={saveState === "saving"}
        >
          {saveLabel}
        </button>
      </div>
    </div>
  );
}
