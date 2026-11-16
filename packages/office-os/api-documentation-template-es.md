# Plantilla de documentación de API interna

## 1. Resumen
*Descripción breve del propósito de la API, su versión y los usuarios principales.*

- **Nombre de la API:** `<Nombre_API>`
- **Versión:** `<YYYY.MM>` o `<v1, v2, ...>`
- **URL base:** `https://<host>/api/<versión>`
- **Contacto:** `nombre <correo>` o `equipo <correo>`
- **Licencia:** `identificador SPDX` o `propietaria`

## 2. Autenticación
*Mecanismo(s) utilizado(s) para asegurar la API.*

| Método | Descripción | Cabeceras / Parámetros |
|---|---|---|
| `Portador JWT` | Token JSON Web emitido tras login/flujo. | `Authorization: Portador <token>` |
| `Clave API` | Clave estática enviada por petición. | `X‑API‑Key: <clave>` o `api_key=<clave>` |
| `OAuth 2.0` | Autorización Código + PKCE o Credenciales de cliente. | `Authorization: Básico <base64>` + `Content‑Type: application/x‑www‑form‑urlencoded` |
| `TLS mutuo` | Certificados mTLS para autenticación mutua. | Certificado cliente en el handshake |

*Opcional:* scopes, renovación de token, revocación.

## 3. Puntos finales
*Lista de rutas disponibles. Convención verb‑nombre consistente.*

| Método | Ruta | Descripción | Autenticación | Cuerpo de petición | Respuesta |
|---|---|---|---|---|---|
| `GET` | `/health` | Comprobación de estado. | Ninguna | — | `200 { status: "ok" }` |
| `POST` | `/auth/login` | Autenticar usuario. | Ninguna | `{ email, password }` | `200 { access_token, refresh_token }` |
| `GET` | `/users` | Listar usuarios. | `Portador` | — | `200 [{ id, name, email }, …]` |
| … | … | … | … | … | … |

*Agrupación lógica de puntos finales (p. ej., `/users`, `/orders`, `/payments`).*

## 4. Ejemplos de Petición / Respuesta
*Mostrar una petición mínima y la respuesta esperada.*

### 4.1. Ejemplo de petición (cURL)
```bash
curl -X GET "$BASE_URL/health" \
  -H "Authorization: Portador <access_token>" \
  -H "Aceptar: application/json"
```

### 4.2. Ejemplo de respuesta (200 OK)
```json
{
  "status": "ok",
  "timestamp": "2025-08-25T12:34:56Z",
  "version": "v1.2.3"
}
```

### 4.3. Respuesta de error (400 Solicitud incorrecta)
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "El campo 'email' es obligatorio.",
    "details": [{ "campo": "email", "razón": "ausente" }]
  }
}
```

## 5. Códigos de Error
*Códigos HTTP estándar más códigos específicos de la aplicación.*

| Código | Significado | Carga de ejemplo |
|---|---|---|
| `400` | Solicitud incorrecta – validación / cuerpo mal formado | `{ "error": { "code": "VALIDATION_FAILED", ... } }` |
| `401` | No autorizado – token falta o inválido | `{ "error": { "code": "UNAUTHORIZED", "message": "Falta token" } }` |
| `403` | Prohibido – scopes insuficientes | `{ "error": { "code": "FORBIDDEN", "message": "Sin acceso" } }` |
| `429` | Demasiadas solicitudes – límite de tasa superado | `{ "error": { "code": "RATE_LIMITED", "message": "…", "retry_after": 60 } }` |
| `500` | Error interno del servidor | `{ "error": { "code": "INTERNAL_ERROR", "message": "Inesperado" } }` |

*Documentar cualquier código de error personal con `code`, `message` y opcionalmente `details` o `retry_after`.*

## 6. Límites de Tasa
*Limitación por punto final o global.*

| Alcance | Límite | Ventana | Cabeceras |
|---|---|---|---|
| **Global** | `100` peticiones | `1` minuto | `X‑RateLimit‑Limit: 100`, `X‑RateLimit‑Remaining: 95`, `X‑RateLimit‑Reset: <ts_unix>` |
| **Por cliente** | `30` peticiones | `1` minuto | Mismas cabeceras que global |
| **Ráfaga** | `10` peticiones | `1` segundo | `Retry-After: 1` (al alcanzar el límite) |

*Indicar cómo los clientes deben manejar las respuestas `429` y el back‑off exponencial.*

## 7. Secciones Adicionales (según sea necesario)
- **Webhooks** – URLs y formato de carga.
- **Paginación** – `page`, `per_page`, cursor `next`.
- **Filtrado / Ordenamiento** – parámetros de consulta.
- **Esquema** – URL de OpenAPI/Swagger o esquema JSON incrustado.

---

### Notas de decisión
- **Formato:** Markdown para legibilidad en repositorios git.
- **Versionado:** Incluir versión de la API en la URL base; puntos finales deprecated marcados con `deprecated: true` y fecha de eliminación.
- **Idioma:** Todos los mensajes de error y cadenas de documentación en inglés neutro (registro estándar). La localización al español se puede proporcionar por separado (ver abajo).
- **Herramientas:** Generar especificación OpenAPI 3.1 a partir de esta plantilla con un script; mantener el markdown sincronizado mediante CI.

### Próximos pasos
1. Poblar la plantilla con la lista real de puntos finales y el flujo de autenticación.
2. Añadir la especificación OpenAPI al lado del markdown.
3. Traducir al español (variantes ibérica y latinoamericana) usando el agente tradutor.
4. Guardar bajo `docs/api/`; enlazar desde el portal interno para desarrolladores.
5. Revisar trimestralmente con el equipo de producto de la API.