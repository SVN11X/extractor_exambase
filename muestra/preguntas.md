# professional data engineer

5 / 349 preguntas. Cobertura completa: False.

Respuestas de la fuente; revisión técnica pendiente. Las imágenes permanecen en sus campos de origen.

5 respuestas conservadas; 0 pendientes.

<a id="topics-105"></a>
## Contexto topics:105
name:
Topic 1


## Pregunta 1

Contexto: [topics:105](#topics-105)
Your company built a TensorFlow neutral-network model with a large number of neurons and layers. The model fits well for the training data. However, when tested against new data, it performs poorly. What method can you employ to address this?

**A.** Threading

**B.** Serialization

**C.** Dropout Methods

**D.** Dimensionality Reduction

**Respuesta de la fuente:** C

**Explicación:** The symptoms described—strong performance on training data but poor performance on new data—are the definition of overfitting. Dropout is a regularization technique that prevents overfitting by randomly disabling neurons during training, forcing the network to learn more robust features and improving generalization. Threading addresses computational speed, serialization handles model persistence, and dimensionality reduction modifies input features, none of which directly solve the structural overfitting issue caused by excessive model complexity.

## Pregunta 2

Contexto: [topics:105](#topics-105)
You are building a model to make clothing recommendations. You know a user's fashion preference is likely to change over time, so you build a data pipeline to stream new data back to the model as it becomes available. How should you use this data to train the model?

**A.** Continuously retrain the model on just the new data.

**B.** Continuously retrain the model on a combination of existing data and the new data.

**C.** Train on the existing data while using the new data as your test set.

**D.** Train on the new data while using the existing data as your test set.

**Respuesta de la fuente:** B

**Explicación:** Option B is correct because retraining on a combination of historical and new data allows the model to adapt to shifting user preferences without suffering from catastrophic forgetting of previously learned patterns. Training solely on new data (Option A) risks losing generalization capability, while using one dataset exclusively for training or testing (Options C and D) violates proper validation protocols and leads to biased performance metrics.

## Pregunta 3

Contexto: [topics:105](#topics-105)
You designed a database for patient records as a pilot project to cover a few hundred patients in three clinics. Your design used a single database table to represent all patients and their visits, and you used self-joins to generate reports. The server resource utilization was at 50%. Since then, the scope of the project has expanded. The database must now store 100 times more patient records. You can no longer run the reports, because they either take too long or they encounter errors with insufficient compute resources. How should you adjust the database design?

**A.** Add capacity (memory and disk space) to the database server by the order of 200.

**B.** Shard the tables into smaller ones based on date ranges, and only generate reports with prespecified date ranges.

**C.** Normalize the master patient-record table into the patient table and the visits table, and create other necessary tables to avoid self-join.

**D.** Partition the table into smaller tables, with one for each clinic. Run queries against the smaller table pairs, and use unions for consolidated reports.

**Respuesta de la fuente:** C

**Explicación:** The current design suffers from poor scalability due to a single table handling both patients and visits with inefficient self-joins. Normalizing the schema into separate tables for patients and visits eliminates data redundancy and removes the performance bottleneck of self-joins, allowing the database to handle the increased volume efficiently. Adding hardware (Option A) does not fix design flaws, while sharding or partitioning by date or clinic (Options B and D) adds unnecessary complexity without addressing the fundamental structural issue.

## Pregunta 4

Contexto: [topics:105](#topics-105)
You create an important report for your large team in Google Data Studio 360. The report uses Google BigQuery as its data source. You notice that visualizations are not showing data that is less than 1 hour old. What should you do?

**A.** Disable caching by editing the report settings.

**B.** Disable caching in BigQuery by editing table details.

**C.** Refresh your browser tab showing the visualizations.

**D.** Clear your browser history for the past hour then reload the tab showing the virtualizations.

**Respuesta de la fuente:** A

**Explicación:** Google Data Studio (Looker Studio) caches data from BigQuery for up to one hour by default to reduce query load and improve performance. To ensure visualizations reflect data less than an hour old, you must disable this caching mechanism in the report settings. This forces the connector to execute a fresh query against BigQuery each time the report loads or is refreshed.

## Pregunta 5

Contexto: [topics:105](#topics-105)
An external customer provides you with a daily dump of data from their database. The data flows into Google Cloud Storage GCS as comma-separated values
(CSV) files. You want to analyze this data in Google BigQuery, but the data could have rows that are formatted incorrectly or corrupted. How should you build this pipeline?

**A.** Use federated data sources, and check data in the SQL query.

**B.** Enable BigQuery monitoring in Google Stackdriver and create an alert.

**C.** Import the data into BigQuery using the gcloud CLI and set max_bad_records to 0.

**D.** Run a Google Cloud Dataflow batch pipeline to import the data into BigQuery, and push errors to another dead-letter table for analysis.

**Respuesta de la fuente:** D

**Explicación:** Option D is correct because Dataflow provides a robust ETL framework capable of validating records during ingestion. By routing malformed rows to a dead-letter table, the pipeline ensures that only clean data enters BigQuery for analysis while preserving error details for debugging. Options A and C fail to handle corruption gracefully (A lacks cleaning logic, C rejects bad records entirely), and Option B is purely for monitoring, not data processing.