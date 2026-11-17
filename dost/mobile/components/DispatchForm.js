/**
 * DispatchForm - submit a prompt to the Dost fleet.
 *
 * Calls api.dispatchTask() on submit and reports status back to the parent
 * through the onDispatch callback.
 */

import React, { useState } from "react";
import {
  View,
  TextInput,
  Button,
  Text,
  ActivityIndicator,
  StyleSheet,
  Alert,
} from "react-native";

import { dispatchTask } from "../api";

export default function DispatchForm({ onDispatch }) {
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState("normal");
  const [loading, setLoading] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const handleSubmit = async () => {
    if (!prompt.trim()) {
      Alert.alert("Empty prompt", "Please enter a prompt before dispatching.");
      return;
    }
    setLoading(true);
    try {
      const result = await dispatchTask(prompt, { priority });
      setLastResult(result);
      if (onDispatch) onDispatch(result);
    } catch (error) {
      Alert.alert("Dispatch failed", error.message || String(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>Dispatch prompt to fleet</Text>
      <TextInput
        style={styles.input}
        value={prompt}
        onChangeText={setPrompt}
        placeholder="e.g. Run a sector rotation scan on Nifty 50"
        multiline
        numberOfLines={3}
      />
      <View style={styles.priorityRow}>
        <Text style={styles.label}>Priority</Text>
        <Button
          title={priority}
          onPress={() =>
            setPriority(priority === "normal" ? "high" : "normal")
          }
          color="#007AFF"
        />
      </View>
      <Button
        title={loading ? "Dispatching..." : "Dispatch to fleet"}
        onPress={handleSubmit}
        disabled={loading}
        color="#007AFF"
      />
      {lastResult && (
        <View style={styles.result}>
          <Text style={styles.subtitle}>Dispatched</Text>
          <Text style={styles.value}>
            {lastResult.task_id || "OK"} (status: {lastResult.status || "queued"})
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#F5F5F7",
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  label: {
    fontSize: 13,
    fontWeight: "600",
    color: "#1D1D1F",
    marginBottom: 6,
  },
  input: {
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: "#D1D1D6",
    borderRadius: 8,
    padding: 10,
    fontSize: 14,
    color: "#1D1D1F",
    marginBottom: 10,
    minHeight: 80,
  },
  priorityRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  result: {
    marginTop: 10,
    padding: 8,
    backgroundColor: "#E6F4EA",
    borderRadius: 8,
  },
  subtitle: {
    fontSize: 12,
    fontWeight: "600",
    color: "#155E33",
    marginBottom: 2,
  },
  value: {
    fontSize: 13,
    color: "#1D1D1F",
  },
});
