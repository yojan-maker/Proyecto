# PUNTO 1 y 2 —  Extracción y Transformación de Datos (Web Scraping + ETL)

# 1. Introducción General

La **Universidad Santo Tomás** se encuentra en un proceso de modernización tecnológica, buscando optimizar sus flujos de trabajo mediante soluciones basadas en **inteligencia artificial**, **visión por computador** y **automatización**.

Dentro de este proceso, se solicitó el diseño e implementación de un sistema capaz de:

* Construir una **base de datos extensa** con imágenes de elementos de laboratorio de electrónica.
* Automatizar el proceso de adquisición mediante técnicas de **web scraping**. 
* Utilizar **concurrencia** (hilos), **semáforos**, **exclusión mutua** y **colas seguras** para incrementar el rendimiento.
* Generar **metadatos consistentes** para su posterior uso en modelos con MediaPipe.

---

Este informe documenta en profundidad la **arquitectura del *software***, los fundamentos teóricos empleados y las **decisiones técnicas** que guiaron el desarrollo.

El énfasis está en la implementación de **hilos**, **semáforos**, **mutex** y **sincronización concurrente**.

---
# 2. Justificación del uso de Web Scraping con Concurrencia

## 2.1. La necesidad de scraping masivo

Cada clase de objeto debía contar con **mínimo 200 imágenes**, y el proyecto incluía inicialmente **10 clases** (multímetro, osciloscopio, protoboard, cautín, fuente de poder, generador de funciones, motor paso a paso, transformador, resistencia, capacitor).

Esto implicaba recolectar **2000 imágenes válidas**, no duplicadas, descargadas, verificadas y almacenadas en el menor tiempo posible.

El *scraping* secuencial se consideró inviable por las siguientes razones:
* **Altísimos tiempos de espera** (latencia de red, en este caso mas de 10 horas para dos clases).
* Dependencia de redes externas lentas.
* Necesidad de **validar imágenes manualmente** (proceso lento).
* **Riesgo alto de bloqueo** por parte del motor de búsqueda (por la alta frecuencia de peticiones desde un único hilo).

> 

La **solución óptima** para cumplir con los requisitos de volumen y tiempo debía ser inherentemente **concurrente**.

---

## 3. Fundamentos Teóricos de Concurrencia Aplicados

Esta sección profundiza en la teoría que fundamenta la implementación utilizada.
# 3.1. Hilos (Threads)

Los **hilos** (`Threads`) permiten ejecutar múltiples tareas de forma **concurrente** dentro de un mismo proceso, compartiendo memoria, variables y archivos.

### Aplicación en este Proyecto
En este proyecto de *web scraping* masivo:
* Cada hilo es un **consumidor** de la cola de URLs.
* Se encarga de descargar una imagen, verificarla, procesarla, guardarla y registrar sus metadatos.

### Ventajas de usar hilos en Web Scraping
El uso de hilos fue crítico debido a que el *scraping* es una tarea limitada por operaciones de Entrada/Salida (**I/O-bound**):

| Ventaja | Descripción |
| :--- | :--- |
| **Alta latencia de red** | Mientras un hilo espera a que se complete una descarga de red, otros pueden avanzar. |
| **CPU poco utilizada** | El proceso está limitado por la I/O, no por procesamiento de CPU. |
| **Bajo consumo de memoria** | Comparado con la creación de múltiples procesos independientes (*multiprocessing*). |
| **Simplicidad de estado** | Es más sencillo compartir y sincronizar el estado global (contador por clase, CSV de metadatos, cola de URLs). |

### Justificación 
El *scraping* es una tarea típicamente I/O-bound, lo cual se beneficia del modelo de hilos incluso con la presencia del **GIL (Global Interpreter Lock)** de Python, ya que:

* El **GIL se libera** durante operaciones de red que esperan datos.
* La descarga de imágenes no compite por tiempo de CPU.
* Los hilos se ejecutan de manera eficiente sin necesidad de recurrir a la complejidad del *multiprocessing*.

---

# 3.2. Exclusión Mutua — Mutex / Lock

**Problema:** Los hilos comparten recursos sensibles, como:

* El archivo **`metadata.csv`** (para registrar los datos).
* Los **contadores de imágenes** por categoría (para nombrar archivos).
* Los índices para nombres de archivos.
* La carpeta donde se guardan las imágenes.

Sin protección, aparece el riesgo de **condiciones de carrera** (*race conditions*).

### 🚨 Ejemplo de Condición de Carrera real:

Dos hilos revisan simultáneamente cuántas imágenes lleva la categoría "multimeter":

```bash
Hilo 1 → ve que hay 50
Hilo 2 → ve que hay 50
Ambos deciden guardar la imagen como multimeter_00051.jpg
```
- Resultado: Se sobrescribe un archivo o se corrompe el dataset.

- Solución:

  - Se implementó:
    ```bash
    counter_lock = threading.Lock()
    ```
  - Este mutex garantiza:

    - Acceso exclusivo a las secciones críticas.

    - Escritura ordenada en metadata.csv.

    - Que solo un hilo manipule los contadores.

    - Generación correcta de nombres de archivos.

    - Evitar duplicados generados por carreras.

  # 3.3. Semaforización — Control de Conexiones Simultáneas

Los **Semáforos** se emplean para **limitar el número de conexiones abiertas simultáneamente** a la red, actuando como un contador de permisos.

### Implementación:
Se utilizó un semáforo para restringir cuántos hilos pueden estar descargando activamente en un momento dado:

```bash
download_semaphore = threading.Semaphore(MAX_SIMULTANEOUS_DOWNLOADS)
```

- ¿Por qué era necesario un Semáforo?

  - El semáforo es crucial para la robustez del scraper debido a los siguientes riesgos:

      - Bloqueo de IPs: Los servicios de imágenes (como Bing) bloquean o imponen CAPTCHAs a IPs que realizan descargas excesivas en paralelo en un corto período de tiempo.

      - Patrón sospechoso: Sin límite, 8 hilos podrían generar 8 conexiones simultáneas cada segundo, lo que se identifica como un patrón de ataque o bot.

      - Saturación: El sistema podría saturar la red local o el motor de búsqueda, provocando timeouts continuos y un rendimiento inestable.

      - Función: El semáforo pone en espera a los hilos que exceden el límite, asegurando que solo un número controlado (MAX_SIMULTANEOUS_DOWNLOADS) acceda a los recursos de red a la vez.

  ### **Cómo funciona**

    - Antes de descargar una imagen:
    ```bash
    download_semaphore.acquire()
    ```
    Cuando finaliza:
    ```bash
    download_semaphore.release()
    ```
  ### **Analizando el impacto**

- Al limitar a 5 conexiones simultáneas se logró:

  - Mantener tráfico estable.

  - Evitar bloqueos por parte del servidor.

  - Permitir a los demás hilos continuar descargando en paralelo.

# 3.4. Cola de Tareas — Productor/Consumidor

La arquitectura se diseñó como:

- Productor

  - Produce URLs obtenidas con Selenium.

  - Las inserta en la cola:
```bash
download_queue.put((url, label))
```
- Consumidores

  - Hilos que obtienen tareas:
```bash
item = download_queue.get()
```
  - Procesan la descarga, verificación, y guardado.

 ## 4. Arquitectura del Sistema Desarrollado

La arquitectura final del sistema de extracción y descarga se estructuró en los siguientes **módulos** principales:

---

### 1. Módulo Selenium

Este módulo es el Productor de tareas, encargado de la extracción de las URLs objetivo.

* **Función:** Extrae cientos de URLs tanto de miniaturas como de las imágenes de alta definición (reales).
* **Mecanismo:** Se desplazó dinámicamente por la plataforma **Bing Images**.
* **Técnica Clave:** Aprovecha el evento de **click en las miniaturas** para exponer y obtener las URLs de las imágenes en calidad HD.

---

### 2. Módulo de Cola de URLs

Actúa como el buffer central entre los módulos de extracción y los de descarga.

* **Función Principal:** Administra el **backlog de trabajo** (las URLs extraídas).
* **Control de Flujo:** Controla el ritmo y el flujo de las tareas que serán entregadas a los **hilos consumidores**.

---

### 3. Módulo Multithreading

Este módulo implementa la concurrencia para la descarga eficiente de archivos.

* **Función:** Ejecuta **múltiples descargas en paralelo** para maximizar el rendimiento.
* **Principio:** Cada hilo de trabajo opera de forma **independiente y segura** al procesar su tarea asignada.

---

### 4. Gestores de Sincronización

Componentes esenciales para garantizar la seguridad y el orden en el entorno concurrente.

* **`Lock`:** Se utiliza para **proteger datos compartidos** de condiciones de carrera (ej., al actualizar un contador global).
* **`Semáforo`:** Se emplea para **controlar las conexiones simultáneas** a la fuente externa, evitando la sobrecarga o el bloqueo por parte del servidor de destino.

---

### 5. Módulo de Metadatos

Asegura la trazabilidad y la integridad de los datos descargados.

* **Almacenamiento:** Guarda la información esencial de cada imagen: **nombre, tamaño, URL y el hash SHA256**.
* **Beneficios:**
    * Asegura la **reproducibilidad** del proceso.
    * Permite la **detección futura de duplicados** de manera infalible.

---

### 6. Depuradores Posteriores

Scripts complementarios ejecutados tras la finalización de las descargas.

* **Función 1:** **Eliminación de imágenes corruptas** o incompletas.
* **Función 2:** Realiza la **deduplicación** final por hash (`SHA256`) utilizando scripts de apoyo.

## 5. Problemas Reales Durante el Desarrollo y Soluciones

Esta sección detalla los principales obstáculos encontrados durante la implementación y las soluciones técnicas aplicadas, lo que demuestra el cumplimiento de objetivos y el aprendizaje técnico adquirido.

---

## 5.1. Descarga de imágenes irrelevantes

El principal desafío en la fase de extracción fue la **baja precisión** de los resultados de búsqueda de la fuente (`Bing Images`).

* **Problema Real:** Al buscar un término técnico y específico como **"multimeter"** (multímetro), la herramienta de búsqueda tendía a devolver imágenes contextualmente irrelevantes, tales como sillas, escritorios o fotografías de personas utilizando el multímetro, en lugar del dispositivo en sí.
* **Soluciones Aplicadas:**
    1.  **Ajuste del Keyword:** Se implementó una estrategia de **ajuste fino de los términos de búsqueda** para intentar acotar los resultados.
    2.  **Curado en Limpieza Posterior:** Se asumió una fase de **curado manual o semiautomático** como parte del proceso de limpieza posterior para descartar imágenes no deseadas.
    3.  **Balance de Dataset:** Posteriormente, para diversificar y mejorar la calidad del conjunto de datos, se añadió el término **"transistor"** a la lista de keywords, buscando **balancear** la tipología de las imágenes.

---

### 5.2. Tiempo excesivo de Extracción (>10 horas)

La optimización del tiempo de ejecución fue crítica, ya que el proceso inicial consumía una cantidad de tiempo inaceptable para la escala de datos requerida.

* **Problema Real:** La extracción de aproximadamente **2000 imágenes limpias** requirió un tiempo de ejecución excesivamente largo, lo que afectó la productividad y la iteración del desarrollo:
    * **5 horas** con Firefox (El proceso falló por errores de perfil del navegador).
    * **Más de 10 horas en total** para completar las extracciones de solo dos clases con la implementación inicial de **Selenium**.
* **Intentos de Solución Fallidos:**
    * Se intentó alternar el *driver* de Selenium entre **Chromium** y **Firefox** para buscar una ganancia de rendimiento, sin éxito significativo.
    * Se evaluaron métodos externos como la librería **`bing_image_downloader`**, pero se descartaron por falta de flexibilidad o control.
* **Solución Final Adoptada (Combinación de Enfoques):**
    1.  **Scraping Multithreading:** Se implementó y optimizó un sistema de **scraping concurrente** utilizando **`multithreading`** para manejar la mayoría de las descargas en paralelo.
    2.  **Herramienta Alternativa Específica:** Se utilizó una **herramienta alternativa específica** para la extracción del subconjunto de imágenes de **"transistores"**, aprovechando su eficiencia para esa tarea concreta.
    3.  **Limpieza Posterior Automática:** La dependencia en una **limpieza posterior automática** se incrementó para manejar la escala de datos extraídos rápidamente, compensando la velocidad de extracción con un proceso de filtrado robusto.

### 5.3. Eliminación masiva — Pérdida del 40–60% de imágenes

Después del dedupe por hash:
  ```bash
  Eliminados: 1189
  ```
- Causas:

  - Imágenes duplicadas en miniaturas/HD.

  - Servidores devolvían la misma imagen con URLs diferentes.

  - Historias de cache del buscador.

- Resultado final:

  - Todas las carpetas quedaron con más de 100 imágenes válidas.
  - Aunque no se alcanzó exactamente 200 por clase, el dataset es consistente y limpio.

  ## 7. Conclusiones del Punto 1: Logros y Aprendizajes

La ejecución exitosa de este proyecto de construcción de dataset y sistema de scraping condujo a los siguientes logros y aprendizajes clave:

---

### Logros del Proyecto

* **Construcción de un Dataset Personalizado para el Laboratorio:** Se logró crear un dataset de alta calidad, curado y específico, con una cantidad de más de 100 imágenes por clase después de la fase de limpieza y depuración.
* **Desarrollo de un Sistema de Scraping Robusto y Realista:** Se diseñó y codificó un sistema de extracción que demostró ser capaz de realizar trabajo intensivo de larga duración, resolviendo desafíos reales de estabilidad y gestión de errores.
* **Implementación de Técnicas Avanzadas de Concurrencia:** Se aplicaron con éxito principios de multithreading y sincronización (Lock, Semaphore) en una aplicación real, con impactos tangibles en la reducción del tiempo de procesamiento.

---

### Aprendizajes Clave

* **Límites y Fallos Comunes del Scraping:** Se obtuvo una experiencia práctica profunda en el manejo y mitigación de problemas intrínsecos al web scraping a gran escala, incluyendo:
    * **Bloqueos de IP:** Estrategias para evadir o manejar las restricciones del servidor fuente.
    * **Imágenes Ruidosas:** Gestión de imágenes con contenido contextual irrelevante.
    * **Contenidos No Relevantes:** Filtrado efectivo de resultados que no cumplen con los requisitos de la clase (ej., errores de keyword).
    * **Duplicados Masivos:** Implementación de hashing (SHA256) para la detección y eliminación eficiente.

* **Generación de una Arquitectura Escalable:** El diseño modular y desacoplado del sistema sentó las bases para la escalabilidad y la integración futura con módulos de Machine Learning para los siguientes objetivos del proyecto:
    * Clasificación con MediaPipe.
    * Reconocimiento de elementos.
    * Implementación del sistema final en Streamlit.

  ---

## 📁 Estructura del proyecto: tree + explicación completa

A continuación se muestra la estructura final del proyecto de Web Scraping con Python, enriquecida con una explicación exhaustiva de cada componente:

**webscrapping/**
* **venv/**
    * ... (Entorno virtual con dependencias)
* **dataset/**
    * [Carpetas de Clases]
        * breadboard/
        * capacitor_electronic_component/
        * diode_electronic_component/
        * function_generator/
        * multimeter/
        * oscilloscope/
        * resistor_electronic_component/
        * soldering_iron/
        * stepper_motor/
        * transistor_electronic_component/
* **metadata/**
    * metadata.csv (Registro formal y trazabilidad del dataset)
* **Archivos Ejecutables y Scripts**
    * scraper\_dataset.py (Scraper PRINCIPAL: Multihilo, Semáforos, Mutex)
    * fast\_download\_transistor.py (Script alterno/de emergencia)
    * check\_corrupt.py (Script para detectar y registrar imágenes dañadas)
    * dedupe\_by\_hash.py (Script para eliminación masiva de duplicados por hash SHA-256)
    * README.md (Documentación principal del proyecto)
  * **Dockerfile**
  * **requirements.txt**

## 🧩 Explicación de las Carpetas y Archivos Principales

A continuación se detalla la función de cada directorio y archivo clave dentro de la estructura del proyecto.

---

### 1. `venv/` — Entorno Virtual 🧪

Este directorio es esencial para la gestión de dependencias del proyecto. 

* **Función Principal:** Contiene todas las **dependencias de Python** de forma aislada del sistema operativo principal.
* **Propósito:**
    * **Evita conflictos de versiones** con librerías o paquetes instalados globalmente en el sistema.
    * Aloja librerías específicas utilizadas en el proyecto, como **`requests`**, **`Pillow`**, **`bing_image_downloader`**, **`beautifulsoup4`**, etc.
    * **Garantiza la portabilidad:** Asegura que cualquier desarrollador que ejecute el proyecto tenga **exactamente el mismo entorno** de trabajo.
* **Estatus:** Es una carpeta indispensable para el desarrollo profesional y reproducible de proyectos en Python.

---

### 2. `dataset/` — Carpetas con las Imágenes Finales 💾

Este directorio almacena la salida principal del proceso de *scraping* y limpieza: el conjunto de datos final.

* **Función Principal:** Contiene todas las **clases (categorías)** que componen el *dataset*.
* **Estructura Interna:** Cada clase se representa mediante una subcarpeta dentro de `dataset/`.
* **Nomenclatura:** Las carpetas de clase tienen un **nombre normalizado** para facilitar el procesamiento posterior por modelos de Machine Learning.

- Ejemplos:

  - breadboard/

  - multimeter/

  - transistor_electronic_component/

  Cada carpeta dentro de `dataset/` contiene las siguientes características después del proceso de curado:

* **Imágenes Válidas:** Solo incluye imágenes que han pasado el proceso de deduplicación (sin duplicados).
* **Imágenes NO Corruptas:** Todos los archivos han sido verificados y garantizan su integridad estructural.
* **Cantidad Final:** **Más de 100 imágenes por clase** después de la limpieza.

> **Nota:** Aunque el objetivo inicial era de 200 imágenes por clase, los desafíos inherentes al *scraping* (problemas de precisión en Bing, el exceso de imágenes basura y la enorme cantidad de duplicados) redujeron el total final. Esta limitación cuantitativa se justifica y explica detalladamente en el **README técnico** del proyecto.

---

### 3. `metadata/metadata.csv` — Registro Formal del Dataset 📄

Este archivo es crucial para la **trazabilidad, auditoría y reproducibilidad** del conjunto de datos. En proyectos serios de *Machine Learning* y análisis de datos, el registro formal del origen y estado de cada muestra es un requisito clave.



**Campos Típicos del `metadata.csv`:**

| Campo | Descripción |
| :--- | :--- |
| `image_path` | La ruta relativa al archivo dentro de la carpeta `dataset/`. |
| `class` | La categoría o etiqueta a la que pertenece la imagen (ej. 'multimeter', 'transistor'). |
| `resolution` | La resolución de la imagen (ej. '640x480'). |
| `file_size` | El tamaño del archivo en bytes. |
| `hash_sha256` | El **hash criptográfico SHA256**, fundamental para la detección de duplicados y la verificación de integridad. |
| `is_corrupt` | Indicador booleano que registra si la imagen fue marcada como corrupta (debería ser **False** para todas las entradas finales). |
| `duplicate_of` | Si es un duplicado, registra el `image_path` del archivo original que se conservó. |

## 4. `scraper_dataset.py` — Scraper PRINCIPAL Multihilo (con Semáforos y Mutex)

Este script es el **archivo más importante y central** de todo el proyecto, conteniendo la lógica de concurrencia y la gestión robusta de errores para la descarga de imágenes.

---

### Funcionalidades Clave y Técnicas de Concurrencia

El script implementa técnicas avanzadas de programación concurrente para optimizar el rendimiento y garantizar la integridad de los datos:

* **Uso de Threads (Hilos):**
    * **Propósito:** Se utilizan para ejecutar la descarga de **múltiples imágenes en paralelo**. 
    * **Impacto:** Sin la concurrencia, el proceso de *scraping* habría tardado un estimado de **40 a 60 horas**.

* **Uso de Semáforos (`Semaphore`):**
    * **Función:** Se implementa un **semáforo** para **limitar el número de descargas simultáneas** a un valor seguro (ejemplo: `semaphore = threading.Semaphore(8)`).
    * **Beneficios:**
        * Evita **bans temporales** por parte de la fuente (`Bing Images`).
        * Previene **errores por saturación** del servidor de destino.
        * Minimiza **timeouts masivos** y el riesgo de saturar la CPU o el ancho de banda local.

* **Uso de Mutex (`Lock`):**
    * **Necesidad:** El mutex (o `Lock`) es necesario porque, aunque las imágenes se descargan en paralelo, **varios hilos deben escribir simultáneamente** en recursos compartidos, como:
        * El archivo de registro de metadatos (`metadata.csv`).
        * **Contadores globales** de progreso o errores.
    * **Resultado:** El uso del mutex **evita *race conditions*** (condiciones de carrera) y previene la **corrupción** del archivo CSV, garantizando la escritura atómica de los datos.

---

### Gestión de Errores y Almacenamiento

El script garantiza la fiabilidad del proceso de descarga mediante control de calidad y robustez:

* **Descarga con Control de Errores Robusto:**
    * **Manejo de Timeouts:** Implementa estrategias de reintento ante fallos de conexión o tiempos de espera agotados.
    * **Retry Automático:** Intenta automáticamente la descarga un número predefinido de veces antes de marcar una tarea como fallida.
    * **Sanitización del Nombre del Archivo:** Procesa y limpia el nombre del archivo para asegurar la compatibilidad con diferentes sistemas operativos.
    * **Verificación de Contenido:** Valida que el archivo descargado sea efectivamente una imagen (ej., contenido tipo `image/jpeg`, `image/png`), descartando posibles archivos HTML o corruptos.

* **Guardado y Organización:** Guarda cada imagen en su **carpeta de clase correspondiente** dentro del directorio `dataset/`, manteniendo la estructura organizada.

### 5. `fast_download_transistor.py` — Script Alterno de Emergencia 🚀

Este script fue desarrollado como una **solución de contingencia** para mitigar los problemas de eficiencia y precisión del *scraper* principal en clases problemáticas.

* **Motivación:** Se creó debido a:
    * El tiempo excesivo de ejecución del *scraper* principal (**más de 10 horas**).
    * El fallo en completar el objetivo de 200 imágenes en algunas clases.
    * La alta tasa de **imágenes irrelevantes** (sillas, autos, etc.) devueltas por Bing.
    * El componente **"transistor"** fue particularmente problemático en la extracción.

* **Implementación:** Utiliza la librería **`bing_image_downloader`**, pero requirió una **modificación interna del módulo** debido a:
    * Un **bug** relacionado con la función `Path.isdir` en el entorno de desarrollo.
    * La necesidad de **adaptar el flujo de descarga** para integrarlo con la estructura de carpetas del proyecto.

* **Uso:** Solo se empleó una vez para **completar una clase puntual** (la de transistores) y balancear el *dataset*.

---

### 6. `check_corrupt.py` — Script para Detectar Imágenes Dañadas 🛡️

Este script de post-procesamiento garantiza la **integridad y usabilidad** de todos los archivos descargados.

* **Mecanismo de Verificación:** Revisa iterativamente cada archivo dentro del directorio `dataset/`.
    * **Proceso:** Intenta abrir la imagen utilizando la librería **PIL (Pillow)**.
    * **Acción:** Si la apertura falla, la imagen es marcada como **corrupta** y el estado se **registra en `metadata.csv`**. Opcionalmente, el script puede ser configurado para eliminar el archivo físicamente.

* **Importancia Crítica:** Este script fue **crucial** porque:
    * Bing entregó una cantidad significativamente alta de **imágenes corruptas** o incompletas.
    * Se detectaron casos de archivos que eran realmente **código HTML disfrazado de JPG** (un error común de *scraping*).

---

### 7. `dedupe_by_hash.py` — Eliminación Masiva de Duplicados ⚙️

Este script asegura la **unicidad** del *dataset*, un paso fundamental para evitar el sesgo en el entrenamiento de modelos de *Machine Learning*.

* **Proceso Central:**
    * **Cálculo de Hash:** Calcula el **hash SHA-256** de cada imagen. Esta es la técnica más robusta y **garantiza detectar duplicados** incluso si los archivos tienen nombres o metadatos distintos. 
    * **Eliminación:** **Elimina automáticamente los duplicados reales**. En la ejecución del proyecto, el resultado fue: **Eliminados: 1189** archivos.

* **Justificación de Duplicados:** La alta tasa de duplicados es normal debido a:
    * La repetición masiva de contenido por parte de la fuente (`Bing`).
    * La similitud entre las clases del *dataset*.
    * La tendencia del buscador a devolver **clones reescalados** de la misma imagen.

* **Registro:** **Actualiza el `metadata.csv`**, marcando cuál archivo fue duplicado de cuál, manteniendo un registro de la limpieza.

![Image](https://github.com/user-attachments/assets/87457fb1-c937-48c2-b33d-3907dcc1ac2c)
>- Carpetas
---

![Image](https://github.com/user-attachments/assets/f716ea5b-7411-4878-80f3-75370a5ab821)
>- Dataset luego del primer web scrapping (sin limpieza)
---


![Image](https://github.com/user-attachments/assets/9ed39431-7098-4396-848e-860c054e8628)
>- Verificación imagenes corruptas
---

![Image](https://github.com/user-attachments/assets/f1d3aa2e-0535-4a78-ab7a-7c0679a83069)
>- Limpieza de imagenes 
---
![Image](https://github.com/user-attachments/assets/7a29297c-70a9-456e-8e5b-2bf1c23a2d70)
>- Limpieza semantica de imagenes ejemplo 1
---

![Image](https://github.com/user-attachments/assets/e6d7a427-5322-43e7-8d54-0ef314cc91fc)
>- Limpieza semantica de imagenes ejemplo 2
---

![Image](https://github.com/user-attachments/assets/3f3d7489-9a38-4b8d-ad4f-1af62686d606)
>- Limpieza semantica de imagenes ejemplo 3
---

![Image](https://github.com/user-attachments/assets/e5b0c03b-132c-475b-97d4-8f8d0a91936d)
>- Cantidad de imagenes despues de la limpieza
---

![Image](https://github.com/user-attachments/assets/80ca9f7a-c417-40f2-b8ef-f4cca9ddaeec)
>- Cantidad de imagenes despues de un nuevo web scrapping y limpieza
---


![Image](https://github.com/user-attachments/assets/3f6283f9-6d0e-4a83-a686-0a926118ed67)
>- Redimension de imágenes y conteo final
---

# Punto 3 - Sistema de Detección en Tiempo Real con Streamlit, YOLO, Seguimiento de Velocidad y Docker 🐳

En este punto  se integra un sistema completo para visión artificial en tiempo real, combinando:

- Detección de personas
- Cálculo de velocidad por seguimiento con Centroid Tracking
- Detección de componentes electrónicos (osciloscopio, multímetro, raspberry…) con YOLO personalizado
- Procesamiento paralelo (multithreading) con semaforización natural usando colas
- Interfaz web en tiempo real desarrollada en Streamlit
- Contenedorización con Docker
- Entrenamiento de un clasificador CNN
- Generación automática de clases

------------

## 🏗️ 1. Arquitectura General del Proyecto

El sistema se divide en módulos independientes que cooperan:    ┌────────────────────────────┐
    │   Streamlit (Frontend)     │
    └──────────────┬─────────────┘
                   │
            Actualización UI
                   │
    ┌──────────────▼──────────────┐
    │        Procesos              │
    │  (Threads independientes)    │
    ├──────────────┬───────────────┤
    │              │               │
    ▼              ▼               ▼
    Captura     Personas         Componentes
      |        (Tracking)           (YOLO)
      |             |                |
      └──────► Cola Q ◄─────────────┘

Cada módulo corre en un hilo separado, sincronizado mediante queues, que funcionan como buffers que evitan bloqueos y regulan el acceso concurrente (semaforización implícita).
