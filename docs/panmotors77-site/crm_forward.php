<?php
/**
 * Отправка заявки с сайта в CRM (panmotors77.ru, Webflow-выгрузка).
 *
 * Подключается из mail.php ПОСЛЕ того, как заявка принята (и письмо отправлено, если оно нужно),
 * и ДО ответа посетителю: см. README.md. Любая ошибка гасится внутри функции, форма не должна
 * падать или зависать из-за CRM. Результат отправки на ответ посетителю не влияет.
 *
 * CRM понимает имена полей этого сайта как есть (Phone number, Name, Форма, Страница, advchannel,
 * Bamper, Kapot, Budget, Summa, Gift, Evakuator, message, ...) и фото в file[] (multipart), ничего
 * переименовывать не нужно. PHP сам заменяет пробелы в именах полей на подчёркивания
 * (Phone number -> Phone_number), CRM это тоже учитывает.
 */

// Адрес приёма заявок в CRM.
const CRM_INTAKE_URL = 'https://piloterist-autoserviceaisolution-8706.twc1.net/api/v1/leads/intake';
// Токен приёма заявок: выдаёт администратор CRM (Настройки -> Заявки). Не хранить в git и не слать в чатах.
const CRM_INTAKE_TOKEN = 'ВСТАВЬТЕ_ТОКЕН_ПРИЁМА_ЗАЯВОК';

const CRM_MAX_PHOTOS = 10;
const CRM_MAX_PHOTO_BYTES = 12 * 1024 * 1024;

/**
 * @param array $post  обычно $_POST
 * @param array $files обычно $_FILES
 * @return bool true, если CRM приняла заявку (HTTP 201)
 */
function crm_forward_lead(array $post, array $files): bool
{
    try {
        if (!function_exists('curl_init')) {
            error_log('CRM lead: на хостинге нет расширения curl');
            return false;
        }

        $fields = [];
        foreach ($post as $key => $value) {
            if (is_array($value)) {
                $value = implode(', ', array_map('strval', $value));
            }
            $fields[$key] = (string) $value;
        }

        // Фото: <input type="file" name="file[]" multiple>. Поля, где файл не выбран (пустое имя,
        // размер 0), пропускаем: именно такой пустой file[] посылает форма квиза без фото.
        $sent = 0;
        if (isset($files['file']['name'])) {
            $names  = (array) $files['file']['name'];
            $tmps   = (array) $files['file']['tmp_name'];
            $errors = (array) $files['file']['error'];
            $sizes  = (array) $files['file']['size'];
            $types  = (array) $files['file']['type'];
            foreach ($names as $i => $name) {
                $tmp   = $tmps[$i] ?? '';
                $error = $errors[$i] ?? UPLOAD_ERR_NO_FILE;
                $size  = (int) ($sizes[$i] ?? 0);
                if ($name === '' || $error !== UPLOAD_ERR_OK || $size <= 0 || !is_uploaded_file($tmp)) {
                    continue;
                }
                if ($size > CRM_MAX_PHOTO_BYTES || $sent >= CRM_MAX_PHOTOS) {
                    continue;
                }
                $mime = $types[$i] ?: 'image/jpeg';
                $fields['file[' . $sent . ']'] = new CURLFile($tmp, $mime, basename($name));
                $sent++;
            }
        }

        $host = isset($_SERVER['HTTP_HOST']) ? $_SERVER['HTTP_HOST'] : 'panmotors77.ru';
        $ch = curl_init(CRM_INTAKE_URL);
        curl_setopt_array($ch, [
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => $fields, // с CURLFile уходит как multipart, без файлов как обычная форма
            CURLOPT_HTTPHEADER     => ['Authorization: Bearer ' . CRM_INTAKE_TOKEN],
            // По этому адресу CRM показывает, с какого сайта пришла заявка (колонка «Сайт»).
            CURLOPT_USERAGENT      => 'SiteLeadForwarder/1.0; https://' . $host,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 4,
            CURLOPT_TIMEOUT        => 15,
        ]);
        $response = curl_exec($ch);
        $code     = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error    = curl_error($ch);
        curl_close($ch);

        // Одна строка в журнале ошибок PHP на заявку: по ней видно, дошла ли она до CRM.
        error_log('CRM lead: http=' . $code . ' photos=' . $sent
            . ($error !== '' ? ' curl_error=' . $error : '')
            . ($code !== 201 ? ' body=' . substr((string) $response, 0, 200) : ''));
        return $code === 201;
    } catch (\Throwable $e) {
        error_log('CRM lead failed: ' . $e->getMessage());
        return false;
    }
}
