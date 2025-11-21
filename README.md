
PUNTO 1 — Web Scrapping

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
