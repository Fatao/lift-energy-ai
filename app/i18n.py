"""Server-side texts in Russian and English.

Everything the backend writes for people (recommendations, explanations, notes) goes through
tr(lang, key, **values). Numbers are formatted by nf() so that the LLM number guard can read
them back (see llm.numbers).
"""

LANGS = ("ru", "en")


def norm(lang):
    return lang if lang in LANGS else "ru"


def nf(lang, x, d=2, group=False):
    """Format a number for people: 1 234,5 (ru) or 1,234.5 (en)."""
    s = f"{x:,.{d}f}" if group else f"{x:.{d}f}"
    if norm(lang) == "ru":
        s = s.replace(",", " ").replace(".", ",")
    return s


CAT = {
    # ---- anomaly events --------------------------------------------------
    "ev.idle": {"ru": "Потребление в простое (поездок нет)", "en": "Consumption while idle (no trips)"},
    "ev.moving": {"ru": "Повышенный расход при движении", "en": "Higher consumption while moving"},

    # ---- recommendations -------------------------------------------------
    "rec.warmup.title": {"ru": "Недостаточно данных для анализа", "en": "Not enough data to analyse"},
    "rec.warmup.text": {
        "ru": "Для оценки простоя и расхода на поездку нужно минимум двое суток почасовых данных, "
              "в которых есть и энергия, и поездки.",
        "en": "Estimating idle draw and energy per trip needs at least two days of hourly data "
              "that contains both energy and trips."},
    "rec.completeness": {"ru": "Полнота данных за {days} сут.: {pct}%", "en": "Data completeness over {days} days: {pct}%"},
    "rec.data.title": {"ru": "Неполные данные", "en": "Incomplete data"},
    "rec.data.text": {
        "ru": "Часть часовых показаний отсутствует. Выводы по этому лифту менее надёжны, пока не будет восстановлена передача данных.",
        "en": "Some hourly readings are missing. Conclusions for this lift are less reliable until the data feed is restored."},
    "rec.standby.title": {"ru": "Повышенное потребление в простое", "en": "High idle consumption"},
    "rec.standby.text": {
        "ru": "Лифт тратит заметно больше энергии без движения, чем остальные в группе. Возможные причины для проверки: "
              "освещение кабины, вентиляция, дисплеи, настройки перехода в режим ожидания. Причину по данным определить нельзя.",
        "en": "This lift uses noticeably more energy while standing still than the rest of the group. Possible causes to check: "
              "cabin lighting, ventilation, displays, standby settings. The data cannot tell the cause."},
    "rec.standby.e1": {
        "ru": "Потребление в простое: {v} кВт против медианы группы {m} кВт (+{p}%)",
        "en": "Idle draw: {v} kW against a group median of {m} kW (+{p}%)"},
    "rec.standby.e2": {
        "ru": "Доля энергии, потраченной в часы без поездок: {p}%",
        "en": "Share of energy used in hours without trips: {p}%"},
    "rec.excess": {"ru": "Оценка перерасхода: ≈{v} кВт·ч в год", "en": "Estimated excess: ≈{v} kWh per year"},
    "rec.per_trip.title": {"ru": "Повышенный расход на одну поездку", "en": "High energy per trip"},
    "rec.per_trip.text": {
        "ru": "На каждую поездку уходит больше энергии, чем у остальных лифтов группы. Возможные причины для проверки: "
              "трение в направляющих, смазка, состояние привода дверей, баланс противовеса.",
        "en": "Each trip uses more energy than on the other lifts in the group. Possible causes to check: "
              "friction in the guides, lubrication, door drive condition, counterweight balance."},
    "rec.per_trip.e1": {
        "ru": "Расход на поездку: {v} кВт·ч против медианы {m} кВт·ч (+{p}%)",
        "en": "Energy per trip: {v} kWh against a median of {m} kWh (+{p}%)"},
    "rec.per_trip.e2": {"ru": "Поездок за {days} сут.: {n}", "en": "Trips in {days} days: {n}"},
    "rec.anomaly.title": {"ru": "Всплеск потребления: {when}", "en": "Consumption surge: {when}"},
    "rec.anomaly.text": {
        "ru": "Энергии потрачено заметно больше, чем объясняют поездки в эти часы. Сверьте интервал с журналом событий "
              "станции управления (ошибки, остановки дверей, нештатные режимы).",
        "en": "Much more energy was used than the trips in these hours explain. Compare the interval with the control "
              "station event log (errors, door stops, abnormal modes)."},
    "rec.anomaly.e1": {"ru": "{kind}, длительность {h} ч", "en": "{kind}, duration {h} h"},
    "rec.anomaly.e2": {
        "ru": "Сверх ожидаемого: {x} кВт·ч, пик {p} кВт·ч за час",
        "en": "Above expected: {x} kWh, peak {p} kWh per hour"},
    "rec.forecast.title": {"ru": "Ожидается рост потребления", "en": "Consumption expected to rise"},
    "rec.forecast.text": {
        "ru": "Прогноз на ближайшую неделю выше фактического потребления за последние 7 суток.",
        "en": "The forecast for the coming week is above actual consumption over the last 7 days."},
    "rec.forecast.e1": {
        "ru": "Факт за 7 сут.: {a} кВт·ч, прогноз: {f} кВт·ч",
        "en": "Actual over 7 days: {a} kWh, forecast: {f} kWh"},

    # ---- forecast ------------------------------------------------------------
    "fc.error": {
        "ru": "Недостаточно истории: нужно минимум 14 полных суток.",
        "en": "Not enough history: at least 14 full days are needed."},
    "fc.method.stat": {
        "ru": "Медиана по дню недели за последние недели × краткосрочный тренд (не более ±10%). Интервал ≈ 80%. "
              "Это статистическая оценка, а не диагностика отказов.",
        "en": "Median by weekday over recent weeks × short-term trend (at most ±10%). Interval ≈ 80%. "
              "This is a statistical estimate, not failure diagnostics."},
    "fc.method.ml": {
        "ru": "Выбрана модель с наименьшей ошибкой на последних {n} сут. (бэктест): {model}. Интервал ≈ 80% по ошибкам "
              "бэктеста. Это оценка потребления, а не диагностика отказов.",
        "en": "The model with the lowest error on the last {n} days (backtest) is used: {model}. The ≈80% interval comes "
              "from backtest errors. This is a consumption estimate, not failure diagnostics."},
    "model.stat": {"ru": "правило: медиана по дню недели × тренд", "en": "rule: weekday median × trend"},
    "model.huber": {"ru": "sklearn: HuberRegressor (день недели + тренд)", "en": "sklearn: HuberRegressor (weekday + trend)"},
    "model.weekday_median": {"ru": "правило: медиана по дню недели", "en": "rule: weekday median"},
    "model.naive7": {"ru": "правило: как неделю назад", "en": "rule: same as a week ago"},

    # ---- LLM -------------------------------------------------------------------
    "llm.system": {
        "ru": "Ты помощник инженера по лифтовому оборудованию. Тебе дают ФАКТЫ в формате JSON, уже посчитанные системой. "
              "Правила: 1) используй только числа и утверждения из фактов, ничего не выдумывай и не пересчитывай; "
              "2) числа переписывай ровно в том виде, как они даны; 3) причины описывай как гипотезы для проверки, "
              "а не как установленный факт; 4) ты не принимаешь решений, решение за инженером; "
              "5) отвечай по-русски, коротко: не более 120 слов, без списков и заголовков.",
        "en": "You are an assistant to a lift maintenance engineer. You are given FACTS as JSON, already computed by the system. "
              "Rules: 1) use only the numbers and statements in the facts; do not invent or recalculate anything; "
              "2) copy numbers exactly as given; 3) describe causes as hypotheses to check, not as established fact; "
              "4) you do not make decisions, the engineer does; "
              "5) answer in English, briefly: at most 120 words, no lists, no headings."},
    "llm.task.rec": {
        "ru": "Объясни инженеру простыми словами, что показывают эти данные и что стоит проверить.",
        "en": "Explain to the engineer in plain words what this data shows and what is worth checking."},
    "llm.task.summary": {
        "ru": "Составь краткую сводку для инженера: общее состояние и на что обратить внимание в первую очередь.",
        "en": "Write a short summary for the engineer: overall condition and what to look at first."},
    "llm.facts": {"ru": "ФАКТЫ", "en": "FACTS"},
    "llm.tpl.rec": {
        "ru": "{lift}: {title}. {text} Основания: {evidence}.{saving} Окончательное решение принимает инженер.",
        "en": "{lift}: {title}. {text} Basis: {evidence}.{saving} The final decision is the engineer's."},
    "llm.tpl.saving": {"ru": " Оценка потенциала: {v} ₽ в год.", "en": " Estimated potential: {v} RUB per year."},
    "llm.tpl.summary1": {
        "ru": "За {days} сут. потреблено {kwh} кВт·ч, аномальных событий: {n}.",
        "en": "Over {days} days {kwh} kWh was used; anomalous events: {n}."},
    "llm.tpl.summary2": {"ru": "Главное: {items}.", "en": "Main points: {items}."},
    "llm.tpl.summary3": {"ru": "Существенных отклонений не найдено.", "en": "No significant deviations found."},
    "llm.tpl.summary4": {"ru": "Решения принимает инженер.", "en": "Decisions are made by the engineer."},
    "llm.note.not_configured": {
        "ru": "ИИ-модель не настроена: показан шаблонный текст по тем же фактам.",
        "en": "No AI model is configured: showing a template text built from the same facts."},
    "llm.note.unavailable": {
        "ru": "ИИ-модель недоступна ({err}): показан шаблонный текст.",
        "en": "The AI model is unavailable ({err}): showing the template text."},
    "llm.note.rejected": {
        "ru": "Ответ модели отклонён: в нём есть числа, которых нет в фактах ({nums}). Показан шаблонный текст.",
        "en": "The model answer was rejected: it contains numbers that are not in the facts ({nums}). Showing the template text."},
    "llm.test.ok": {"ru": "Подключение работает.", "en": "Connection works."},
    "llm.test.none": {"ru": "ИИ-провайдер не выбран.", "en": "No AI provider is selected."},
    "llm.test.nokey": {"ru": "Не указан ключ или адрес.", "en": "The key or address is missing."},

    # ---- import ----------------------------------------------------------------
    "imp.empty": {"ru": "Файл пустой.", "en": "The file is empty."},
    "imp.xls": {
        "ru": "Старый формат .xls не поддерживается. Сохраните файл как .xlsx или .csv.",
        "en": "The old .xls format is not supported. Save the file as .xlsx or .csv."},
    "imp.bad_file": {
        "ru": "Не удалось прочитать файл: {err}. Поддерживаются .csv и .xlsx.",
        "en": "The file could not be read: {err}. Supported formats: .csv and .xlsx."},
    "imp.no_ts": {"ru": "Не найдена колонка со временем.", "en": "No time column was found."},
    "imp.no_value": {
        "ru": "Не найдена колонка с энергией (кВт·ч) или поездками.",
        "en": "No energy (kWh) or trips column was found."},
    "imp.no_lift": {
        "ru": "В файле нет колонки с номером лифта. Укажите, к какому лифту относятся данные.",
        "en": "The file has no lift column. Say which lift the data belongs to."},
    "imp.no_rows": {"ru": "Не найдено ни одной корректной строки.", "en": "No valid rows were found."},
    "imp.not_hourly": {
        "ru": "Данные не почасовые (типичный шаг около {m} мин). Анализ рассчитан на почасовые показания, "
              "результаты по таким данным будут неточными.",
        "en": "The data is not hourly (typical step about {m} min). The analysis expects hourly readings, "
              "so results on this data will be inaccurate."},
    "imp.cumulative_first": {
        "ru": "Для накопительных счётчиков первая строка каждого лифта служит точкой отсчёта и в данные не попадает.",
        "en": "For cumulative counters the first row of each lift is only a baseline and is not stored."},
}


def tr(lang, key, **kw):
    entry = CAT[key]
    text = entry[norm(lang)]
    return text.format(**kw) if kw else text