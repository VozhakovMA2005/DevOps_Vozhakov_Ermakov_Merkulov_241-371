# Протокол фактического прогона ЛР6

Заполнить после выполнения; пустое поле не подтверждает успех.

| Поле | Значение |
|---|---|
| Дата и время UTC | |
| Участник, реальная Issue, ветка, PR | |
| CI URL и результат всех стадий | |
| Publish job и registry tag/digest | |
| SHA main и /version до/после | |
| deploy job URL, exit code | |
| healthy db/app/nginx | |
| healthz/readyz HTTP status | |
| version+commit совпали | |
| Вход, непустой каталог, карточка | |
| Неверный/отсутствующий тег | |
| Отсутствующая переменная | |
| Неуспешный healthcheck | |
| Сбой каталога при healthy | |
| Недоступный registry | |
| Автоматический возврат после отказа | |
| Ручной rollback: previous digest → current | |
| Конфликт/прерывание и recover | |
| Аннотированный release tag | |

Приложить обезличенные фрагменты release-history; не вставлять env и токены.
