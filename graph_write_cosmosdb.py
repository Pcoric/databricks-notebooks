# Databricks notebook source
# MAGIC %md # Writing GraphFrames to Azure Cosmos DB Gremlin API
# MAGIC This notebook is based on the `GraphFrames` example [specified here](https://docs.azuredatabricks.net/spark/latest/graph-analysis/graphframes/user-guide-python.html). It requires [graphframes](https://spark-packages.org/package/graphframes/graphframes) and [azure-cosmosdb-spark (uber jar)](http://repo1.maven.org/maven2/com/microsoft/azure/azure-cosmosdb-spark_2.3.0_2.11/1.2.6/) libraries to be uploaded and attached to the cluster. **Scala version** of this notebook can be [found here](https://github.com/syedhassaanahmed/databricks-notebooks/blob/master/graphWriteCosmosDB.scala)

# COMMAND ----------

from pyspark.sql.functions import *

v = sqlContext.createDataFrame([
  ("a", "Alice", 34),
  ("b", "Bob", 36),
  ("c", "Charlie", 30),
  ("d", "David", 29),
  ("e", "Esther", 32),
  ("f", "Fanny", 36),
  ("g", "Gabby", 60)
], ["id", "name", "age"]) \
.withColumn("entity", lit("person"))

# COMMAND ----------

e = sqlContext.createDataFrame([
  ("a", "b", "friend"),
  ("b", "c", "follow"),
  ("c", "b", "follow"),
  ("f", "c", "follow"),
  ("e", "f", "follow"),
  ("e", "d", "friend"),
  ("d", "a", "friend"),
  ("a", "e", "friend")
], ["src", "dst", "relationship"])

# COMMAND ----------

from graphframes import *
g = GraphFrame(v, e)
display(g.vertices)

# COMMAND ----------

# MAGIC %md ## Convert Vertices and Edges to Cosmos DB internal format
# MAGIC Cosmos DB Gremlin API internally keeps a JSON document representation of Edges and Vertices [as explained here](https://vincentlauzon.com/2017/09/05/hacking-accessing-a-graph-in-cosmos-db-with-sql-documentdb-api/). Also `id` in Cosmos DB is [part of the resource URI](https://github.com/Azure/azure-cosmosdb-dotnet/issues/35#issuecomment-121009258) and hence must be URL encoded.

# COMMAND ----------

from pyspark.sql.types import *
from urllib.parse import quote

def urlencode(value):
  return quote(value, safe="")

udf_urlencode = udf(urlencode, StringType())

# COMMAND ----------

def to_cosmosdb_vertices(dfVertices, labelColumn, partitionKey = ""):
  dfVertices = dfVertices.withColumn("id", udf_urlencode("id"))
  
  columns = ["id", labelColumn]
  
  if partitionKey:
    columns.append(partitionKey)
  
  columns.extend(['nvl2({x}, array(named_struct("id", uuid(), "_value", {x})), NULL) AS {x}'.format(x=x) \
                for x in dfVertices.columns if x not in columns])
 
  return dfVertices.selectExpr(*columns).withColumnRenamed(labelColumn, "label")

# COMMAND ----------

cosmosDbVertices = to_cosmosdb_vertices(g.vertices, "entity")
display(cosmosDbVertices)

# COMMAND ----------

def to_cosmosdb_edges(g, labelColumn, partitionKey = ""): 
  dfEdges = g.edges
  
  if partitionKey:
    dfEdges = dfEdges.alias("e") \
      .join(g.vertices.alias("sv"), col("e.src") == col("sv.id")) \
      .join(g.vertices.alias("dv"), col("e.dst") == col("dv.id")) \
      .selectExpr("e.*", "sv." + partitionKey, "dv." + partitionKey + " AS _sinkPartition")

  dfEdges = dfEdges \
    .withColumn("id", udf_urlencode(concat_ws("_", col("src"), col(labelColumn), col("dst")))) \
    .withColumn("_isEdge", lit(True)) \
    .withColumn("_vertexId", udf_urlencode("src")) \
    .withColumn("_sink", udf_urlencode("dst")) \
    .withColumnRenamed(labelColumn, "label") \
    .drop("src", "dst")
  
  return dfEdges

# COMMAND ----------

cosmosDbEdges = to_cosmosdb_edges(g, "relationship")
display(cosmosDbEdges)

# COMMAND ----------

cosmosDbConfig = {
  "Endpoint" : "https://<COSMOSDB_ENDPOINT>.documents.azure.com:443/",
  "Masterkey" : "<COSMOSDB_PRIMARYKEY>",
  "Database" : "<DATABASE>",
  "Collection" : "<COLLECTION>",
  "Upsert" : "true"
}

cosmosDbFormat = "com.microsoft.azure.cosmosdb.spark"

cosmosDbVertices.write.format(cosmosDbFormat).mode("append").options(**cosmosDbConfig).save()
cosmosDbEdges.write.format(cosmosDbFormat).mode("append").options(**cosmosDbConfig).save()

# COMMAND ----------


