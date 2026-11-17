/**
 * TaskList - display recent Dost tasks.
 *
 * Accepts an array of task objects (from api.getTasks()) and renders each
 * with its id, agent, status, and created timestamp.
 */

import React from "react";
import { View, Text, FlatList, StyleSheet, ActivityIndicator } from "react-native";

const EMPTY_AGENT = "—";

export default function TaskList({ tasks = [], loading = false, onRefresh }) {
  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#007AFF" />
      </View>
    );
  }

  if (tasks.length === 0) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyText}>No recent tasks</Text>
      </View>
    );
  }

  const renderItem = ({ item }) => (
    <View style={styles.row}>
      <View style={styles.body}>
        <Text style={styles.taskId}>{item.task_id || item.id || "unknown"}</Text>
        <Text style={styles.meta}>
          {item.agent_id || EMPTY_AGENT} • {item.status || "unknown"}
        </Text>
        <Text style={styles.meta}>
          {item.created_at || ""}
        </Text>
      </View>
      <View style={styles.badge}>
        <Text style={styles.badgeText}>{item.status || "?"}</Text>
      </View>
    </View>
  );

  const keyExtractor = (item) => item.task_id || item.id || String(Math.random());

  return (
    <View style={styles.container}>
      <FlatList
        data={tasks}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        contentContainerStyle={styles.listContent}
        onRefresh={onRefresh}
        refreshing={loading}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  listContent: {
    paddingVertical: 8,
  },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 10,
    paddingHorizontal: 14,
    backgroundColor: "#FFFFFF",
  },
  separator: {
    height: 1,
    backgroundColor: "#E5E5EA",
    marginLeft: 14,
  },
  body: {
    flex: 1,
  },
  taskId: {
    fontSize: 14,
    fontWeight: "600",
    color: "#1D1D1F",
  },
  meta: {
    fontSize: 12,
    color: "#86868B",
    marginTop: 2,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    backgroundColor: "#E5E5EA",
  },
  badgeText: {
    fontSize: 11,
    fontWeight: "600",
    color: "#1D1D1F",
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  empty: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  emptyText: {
    fontSize: 14,
    color: "#86868B",
  },
});
