# Общие настройки проксирования к экземплярам приложения.
# Расширение .inc, а не .conf: сам по себе файл не подключается, только
# через include из default.conf.

proxy_pass http://audfond;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-Id $request_id;

# Повтор запроса на другом узле (доп. пункт 7). Повторяются только
# безопасные запросы (GET, HEAD): POST загрузки реестра повторно не
# отправляется, иначе импорт мог бы выполниться дважды
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 2;
proxy_next_upstream_timeout 10s;

proxy_connect_timeout 2s;
# proxy_read_timeout задаётся в каждом location: у загрузки реестра он больше

# Какой узел ответил — видно в заголовке рядом с X-Instance от приложения
add_header X-Upstream $upstream_addr always;
