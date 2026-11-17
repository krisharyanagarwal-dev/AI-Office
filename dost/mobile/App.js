/**
 * App.js - Main component for Dost Mobile.
 *
 * Fleet status display (completion rate, error rate, pools available),
 * dispatch prompt input, debate button, and a results list of recent tasks.
 *
 * Talks to the Dost fleet API at http://127.0.0.1:8083 via api.js.
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { getMetrics, startDebate, getTasks, healthCheck } from "./api";
import DispatchForm from "./components/DispatchForm";
import TaskList from "./components/TaskList";

export default function App() {
  const [status, setStatus] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [debateLoading, setDebateLoading] = useState(false);
  const [health, setHealth] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [metrics, taskList, fleetHealth] = await Promise.all([
        getMetrics(),
        getTasks(),
        healthCheck(),
      ]);
      setStatus(metrics);
      setTasks(Array.isArray(taskList) ? taskList : []);
      setHealth(fleetHealth);
    } catch (error) {
      // Fleet may not be running; show empty state rather than crashing.
      console.warn("Failed to refresh fleet status:", error.message);
      setStatus(null);
      setTasks([]);
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleDebate = async () => {
    setDebateLoading(true);
    try {
      await startDebate("Office fleet status check", [
        "strategy-advisor",
        "cost-analyst",
        "risk-manager",
      ]);
      Alert.alert("Debate started", "Multi-agent debate dispatched to the fleet.");
      await refresh();
    } catch (error) {
      Alert.alert("Debate failed", error.message || String(error));
    } finally {
      setDebateLoading(false);
    }
  };

  const onDispatch = useCallback(() => {
    refresh();
  }, [refresh]);

  const pools = (status && status.provider_pools) || {};
  const poolNames = Object.keys(pools);
  const poolsAvailable = poolNames.filter(
    (name) => (pools[name] && pools[name].cooldown_remaining) === 0
  ).length;
  const tasksCreated = status && status.tasks_created ? status.tasks_created : 0;
  const tasksDone = status && status.tasks_done ? status.tasks_done : 0;
  const completionRate =
    tasksCreated > 0 ? ((tasksDone / tasksCreated) * 100).toFixed(0) : 0;
  const errorCount = status && status.errors ? status.errors : 0;
  const errorRate = tasksCreated > 0 ? ((errorCount / tasksCreated) * 100).toFixed(0) : 0;

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color="#007AFF" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.header}>
          <Text style={styles.appTitle}>Dost Mobile</Text>
          <Text style={styles.appSubtitle}>THE CLAUDE COMPANY • Office Fleet</Text>
        </View>

        {/* Fleet status */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Fleet status</Text>
          <View style={styles.statRow}>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{completionRate}%</Text>
              <Text style={styles.statLabel}>Completion rate</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{errorRate}%</Text>
              <Text style={styles.statLabel}>Error rate</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{poolsAvailable}</Text>
              <Text style={styles.statLabel}>Pools available</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>
                {health ? (health.status || "ok") : "unknown"}
              </Text>
              <Text style={styles.statLabel}>Health</Text>
            </View>
          </View>
          <View style={styles.poolsList}>
            <Text style={styles.poolsLabel}>Provider pools</Text>
            {poolNames.length === 0 ? (
              <Text style={styles.poolsEmpty}>None reported</Text>
            ) : (
              poolNames.map((name) => {
                const info = pools[name] || {};
                const cooling = (info.cooldown_remaining || 0) > 0;
                return (
                  <View key={name} style={[styles.poolRow, cooling && styles.poolCooling]}>
                    <Text style={styles.poolName}>{name}</Text>
                    <Text style={[styles.poolStatus, cooling && styles.poolStatusCooling]}>
                      {cooling ? `Cooling down (${info.cooldown_remaining}s)` : "Available"}
                    </Text>
                  </View>
                );
              })
            )}
          </View>
        </View>

        {/* Actions */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Actions</Text>
          <DispatchForm onDispatch={onDispatch} />
          <TouchableOpacity
            style={[styles.button, styles.buttonDebate]}
            onPress={handleDebate}
            disabled={debateLoading}
          >
            <Text style={styles.buttonText}>
              {debateLoading ? "Starting debate..." : "Start debate"}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Results list */}
        <View style={styles.card}>
          <View style={styles.listHeader}>
            <Text style={styles.sectionTitle}>Recent dost tasks</Text>
            <TouchableOpacity
              style={styles.refresh}
              onPress={refresh}
              disabled={loading}
            >
              <Text style={styles.refreshText}>↻</Text>
            </TouchableOpacity>
          </View>
          <TaskList tasks={tasks} loading={loading} onRefresh={refresh} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F5F5F7",
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 24,
  },
  header: {
    marginBottom: 16,
  },
  appTitle: {
    fontSize: 24,
    fontWeight: "700",
    color: "#1D1D1F",
  },
  appSubtitle: {
    fontSize: 13,
    color: "#86868B",
    marginTop: 2,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: "600",
    color: "#1D1D1F",
    marginBottom: 10,
  },
  statRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 12,
  },
  stat: {
    alignItems: "center",
    flex: 1,
  },
  statValue: {
    fontSize: 20,
    fontWeight: "700",
    color: "#007AFF",
  },
  statLabel: {
    fontSize: 11,
    color: "#86868B",
    marginTop: 2,
  },
  poolsList: {
    marginTop: 2,
  },
  poolsLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: "#86868B",
    marginBottom: 6,
  },
  poolRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 5,
    borderBottomWidth: 1,
    borderBottomColor: "#F0F0F3",
  },
  poolCooling: {
    opacity: 0.6,
  },
  poolName: {
    fontSize: 13,
    color: "#1D1D1F",
  },
  poolStatus: {
    fontSize: 11,
    fontWeight: "600",
    color: "#155E33",
  },
  poolStatusCooling: {
    color: "#B45309",
  },
  poolsEmpty: {
    fontSize: 12,
    color: "#86868B",
  },
  listHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  refresh: {
    padding: 4,
  },
  refreshText: {
    fontSize: 16,
    color: "#007AFF",
  },
  button: {
    backgroundColor: "#007AFF",
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 10,
  },
  buttonDebate: {
    backgroundColor: "#AF52DE",
  },
  buttonText: {
    color: "#FFFFFF",
    fontSize: 15,
    fontWeight: "600",
  },
});
