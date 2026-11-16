"""
Neural Network Models
MLP, LSTM, and Transformer models
"""
import pandas as pd
import numpy as np
from typing import List, Optional, Dict, Any

from .base import BaseModel


class MLPModel(BaseModel):
    """
    Multi-Layer Perceptron (Neural Network)
    """
    
    def __init__(
        self,
        hidden_layers: List[int] = [64, 32],
        activation: str = 'relu',
        dropout_rate: float = 0.2,
        learning_rate: float = 0.001,
        batch_size: int = 32,
        epochs: int = 100,
        **kwargs
    ):
        super().__init__(name="MLPModel", **kwargs)
        self.hidden_layers = hidden_layers
        self.activation = activation
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epsilog = epochs
        self.model = None
        self.is_fitted = False
        self.scaler_X = None
        self.scaler_y = None
        
        # Try to import tensorflow or torch
        try:
            import tensorflow as tf
            self.tf = tf
            self.framework = 'tensorflow'
        except ImportError:
            try:
                import torch
                self.torch = torch
                self.nn = torch.nn
                self.optim = torch.optim
                self.framework = 'pytorch'
            except ImportError:
                raise ImportError("Neither tensorflow nor torch is installed. Install one of: pip install tensorflow or pip install torch")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        from sklearn.preprocessing import StandardScaler
        
        # Handle missing values
        X_clean = X.fillna(0).values
        y_clean = y.fillna(0).values.reshape(-1, 1)
        
        # Scale features and target
        self.scaler_X = StandardScaler()
        self.scaler_y = StandardScaler()
        X_scaled = self.scaler_X.fit_transform(X_clean)
        y_scaled = self.scaler_y.fit_transform(y_clean).flatten()
        
        if self.framework == 'tensorflow':
            self._fit_tensorflow(X_scaled, y_scaled)
        else:
            self._fit_pytorch(X_scaled, y_scaled)
        
        self.is_fitted = True
        return self
    
    def _fit_tensorflow(self, X: np.ndarray, y: np.ndarray):
        """Fit using TensorFlow/Keras"""
        # Build model
        model = self.tf.keras.Sequential()
        
        # Input layer
        model.add(self.tf.keras.layers.Dense(
            self.hidden_layers[0],
            activation=self.activation,
            input_shape=(X.shape[1],)
        ))
        model.add(self.tf.keras.layers.Dropout(self.dropout_rate))
        
        # Hidden layers
        for units in self.hidden_layers[1:]:
            model.add(self.tf.keras.layers.Dense(
                units,
                activation=self.activation
            ))
            model.add(self.tf.keras.layers.Dropout(self.dropout_rate))
        
        # Output layer
        model.add(self.tf.keras.layers.Dense(1))
        
        # Compile model
        model.compile(
            optimizer=self.tf.keras.optimizers.Adam(learning_rate=self.learning_rate),
            loss='mse',
            metrics=['mae']
        )
        
        # Train model
        model.fit(
            X, y,
            batch_size=self.batch_size,
            epochs=self.epsilog,
            verbose=0
        )
        
        self.model = model
    
    def _fit_pytorch(self, X: np.ndarray, y: np.ndarray):
        """Fit using PyTorch"""
        # Convert to tensors
        X_tensor = self.torch.FloatTensor(X)
        y_tensor = self.torch.FloatTensor(y)
        
        # Create dataset and dataloader
        dataset = self.torch.utils.data.TensorDataset(X_tensor, y_tensor)
        dataloader = self.torch.utils.data.DataLoader(
            dataset, batch_size=self.batch_size, shuffle=True
        )
        
        # Build model
        layers = []
        prev_size = X.shape[1]
        
        for units in self.hidden_layers:
            layers.append(self.nn.Linear(prev_size, units))
            if self.activation == 'relu':
                layers.append(self.nn.ReLU())
            elif self.activation == 'tanh':
                layers.append(self.nn.Tanh())
            layers.append(self.nn.Dropout(self.dropout_rate))
            prev_size = units
        
        # Output layer
        layers.append(self.nn.Linear(prev_size, 1))
        
        self.model = self.nn.Sequential(*layers)
        
        # Loss and optimizer
        criterion = self.nn.MSELoss()
        optimizer = self.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        
        # Train model
        self.model.train()
        for epoch in range(self.epsilog):
            for batch_X, batch_y in dataloader:
                optimizer.zero_grad()
                outputs = self.model(batch_X)
                loss = criterion(outputs.squeeze(), batch_y)
                loss.backward()
                optimizer.step()
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Handle missing values
        X_clean = X.fillna(0).values
        
        # Scale features
        X_scaled = self.scaler_X.transform(X_clean)
        
        if self.framework == 'tensorflow':
            predictions_scaled = self.model.predict(X_scaled, verbose=0)
        else:
            self.model.eval()
            with self.torch.no_grad():
                X_tensor = self.torch.FloatTensor(X_scaled)
                predictions_scaled = self.model(X_tensor).numpy()
        
        # Inverse transform predictions
        predictions = self.scaler_y.inverse_transform(predictions_scaled.reshape(-1, 1)).flatten()
        
        return pd.Series(predictions, index=X.index, name=self.name)


class LSTMModel(BaseModel):
    """
    Long Short-Term Memory (LSTM) for sequential data
    """
    
    def __init__(
        self,
        sequence_length: int = 10,
        hidden_units: int = 50,
        dropout_rate: float = 0.2,
        learning_rate: float = 0.001,
        batch_size: int = 32,
        epochs: int = 50,
        **kwargs
    ):
        super().__init__(name="LSTMModel", **kwargs)
        self.sequence_length = sequence_length
        self.hidden_units = hidden_units
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.model = None
        self.is_fitted = False
        self.scaler_X = None
        self.scaler_y = None
        
        # Try to import tensorflow or torch
        try:
            import tensorflow as tf
            self.tf = tf
            self.framework = 'tensorflow'
        except ImportError:
            try:
                import torch
                self.torch = torch
                self.nn = torch.nn
                self.optim = torch.optim
                self.framework = 'pytorch'
            except ImportError:
                raise ImportError("Neither tensorflow nor torch is installed. Install one of: pip install tensorflow or pip install torch")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model - expects X to be already sequenced or will create sequences"""
        from sklearn.preprocessing import StandardScaler
        
        # Handle missing values
        X_clean = X.fillna(0).values
        y_clean = y.fillna(0).values.reshape(-1, 1)
        
        # Create sequences if needed
        if len(X_clean) > self.sequence_length:
            X_seq, y_seq = self._create_sequences(X_clean, y_clean.flatten())
        else:
            # Not enough data for sequences
            X_seq = X_clean
            y_seq = y_clean.flatten()
        
        # Scale features and target
        self.scaler_X = StandardScaler()
        self.scaler_y = StandardScaler()
        X_scaled = self.scaler_X.fit_transform(X_seq)
        y_scaled = self.scaler_y.fit_transform(y_seq.reshape(-1, 1)).flatten()
        
        if self.framework == 'tensorflow':
            self._fit_tensorflow(X_scaled, y_scaled)
        else:
            self._fit_pytorch(X_scaled, y_scaled)
        
        self.is_fitted = True
        return self
    
    def _create_sequences(self, X: np.ndarray, y: np.ndarray):
        """Create sequences for LSTM"""
        Xs, ys = [], []
        for i in range(len(X) - self.sequence_length):
            Xs.append(X[i:(i + self.sequence_length)])
            ys.append(y[i + self.sequence_length])
        return np.array(Xs), np.array(ys)
    
    def _fit_tensorflow(self, X: np.ndarray, y: np.ndarray):
        """Fit using TensorFlow/Keras"""
        # Build model
        model = self.tf.keras.Sequential()
        
        # LSTM layer
        model.add(self.tf.keras.layers.LSTM(
            self.hidden_units,
            return_sequences=False,
            input_shape=(X.shape[1], X.shape[2]) if len(X.shape) == 3 else (X.shape[1], 1)
        ))
        model.add(self.tf.keras.layers.Dropout(self.dropout_rate))
        
        # Output layer
        model.add(self.tf.keras.layers.Dense(1))
        
        # Compile model
        model.compile(
            optimizer=self.tf.keras.optimizers.Adam(learning_rate=self.learning_rate),
            loss='mse',
            metrics=['mae']
        )
        
        # Train model
        model.fit(
            X, y,
            batch_size=self.batch_size,
            epochs=self.epochs,
            verbose=0
        )
        
        self.model = model
    
    def _fit_pytorch(self, X: np.ndarray, y: np.ndarray):
        """Fit using PyTorch"""
        # Reshape for LSTM if needed
        if len(X.shape) == 2:
            X = X.reshape((X.shape[0], 1, X.shape[1]))  # (batch, seq_len, features)
        
        # Convert to tensors
        X_tensor = self.torch.FloatTensor(X)
        y_tensor = self.torch.FloatTensor(y)
        
        # Create dataset and dataloader
        dataset = self.torch.utils.data.TensorDataset(X_tensor, y_tensor)
        dataloader = self.torch.utils.data.DataLoader(
            dataset, batch_size=self.batch_size, shuffle=True
        )
        
        # Build model
        self.model = self.nn.LSTM(
            input_size=X.shape[2],
            hidden_size=self.hidden_units,
            num_layers=1,
            batch_first=True,
            dropout=self.dropout_rate
        )
        
        # Output layer
        self.fc = self.nn.Linear(self.hidden_units, 1)
        
        # Loss and optimizer
        criterion = self.nn.MSELoss()
        optimizer = self.optim.Adam(list(self.model.parameters()) + list(self.fc.parameters()), lr=self.learning_rate)
        
        # Train model
        self.model.train()
        for epoch in range(self.epochs):
            for batch_X, batch_y in dataloader:
                optimizer.zero_grad()
                lstm_out, _ = self.model(batch_X)
                # Take last time step output
                output = self.fc(lstm_out[:, -1, :])
                loss = criterion(output.squeeze(), batch_y)
                loss.backward()
                optimizer.step()
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Handle missing values
        X_clean = X.fillna(0).values
        
        # Create sequences if needed
        if len(X_clean) > self.sequence_length:
            X_seq, _ = self._create_sequences(X_clean, np.zeros(len(X_clean)))
        else:
            X_seq = X_clean
        
        # Scale features
        X_scaled = self.scaler_X.transform(X_seq.reshape(-1, X_seq.shape[-1]) if len(X_seq.shape) == 3 else X_seq)
        if len(X_seq.shape) == 3:
            X_scaled = X_scaled.reshape(X_seq.shape)
        
        if self.framework == 'tensorflow':
            predictions_scaled = self.model.predict(X_scaled, verbose=0)
        else:
            self.model.eval()
            with self.torch.no_grad():
                X_tensor = self.torch.FloatTensor(X_scaled)
                lstm_out, _ = self.model(X_tensor)
                # Take last time step output
                predictions_scaled = self.fc(lstm_out[:, -1, :]).numpy()
        
        # Inverse transform predictions
        predictions = self.scaler_y.inverse_transform(predictions_scaled.reshape(-1, 1)).flatten()
        
        # For sequence models, we need to align predictions with original indices
        # The prediction corresponds to the point after the sequence
        if len(X_clean) > self.sequence_length:
            # Create full series of predictions
            full_predictions = np.full(len(X_clean), np.nan)
            # Predictions start at index sequence_length
            full_predictions[self.sequence_length:] = predictions
            result_series = pd.Series(full_predictions, index=X.index)
        else:
            # Not enough data for sequences, predict on available data
            result_series = pd.Series(predictions, index=X.index[:len(predictions)])
        
        return result_series


class TransformerModel(BaseModel):
    """
    Transformer model (simplified version)
    """
    
    def __init__(
        self,
        sequence_length: int = 10,
        d_model: int = 64,
        n_heads: int = 4,
        num_layers: int = 2,
        dropout_rate: float = 0.1,
        learning_rate: float = 0.001,
        batch_size: int = 32,
        epochs: int = 50,
        **kwargs
    ):
        super().__init__(name="TransformerModel", **kwargs)
        self.sequence_length = sequence_length
        self.d_model = d_model
        self.n_heads = n_heads
        self.num_layers = num_layers
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.batch_size = batch_size
        self.epochs = epochs
        self.model = None
        self.is_fitted = False
        self.scaler_X = None
        self.scaler_y = None
        
        # Try to import tensorflow or torch
        try:
            import tensorflow as tf
            self.tf = tf
            self.framework = 'tensorflow'
        except ImportError:
            try:
                import torch
                self.torch = torch
                self.nn = torch.nn
                self.optim = torch.optim
                self.framework = 'pytorch'
            except ImportError:
                raise ImportError("Neither tensorflow nor torch is installed. Install one of: pip install tensorflow or pip install torch")
    
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs):
        """Fit the model"""
        # For now, fall back to MLP implementation for simplicity
        # A full transformer implementation is quite complex
        mlp_model = MLPModel(
            hidden_layers=[self.d_model, self.d_model//2],
            dropout_rate=self.dropout_rate,
            learning_rate=self.learning_rate,
            batch_size=self.batch_size,
            epochs=self.epochs
        )
        mlp_model.fit(X, y, **kwargs)
        self.model = mlp_model.model
        self.scaler_X = mlp_model.scaler_X
        self.scaler_y = mlp_model.scaler_y
        self.framework = mlp_model.framework
        self.is_fitted = True
        return self
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions"""
        if not self.is_fitted:
            raise ValueError("Model must be fitted before making predictions")
        
        # Delegate to MLP model
        # In a real implementation, this would use the actual transformer
        mlp_model = MLPModel(
            hidden_layers=[self.d_model, self.d_model//2],
            dropout_rate=self.dropout_rate,
            learning_rate=self.learning_rate,
            batch_size=self.batch_size,
            epochs=self.epochs
        )
        mlp_model.model = self.model
        mlp_model.scaler_X = self.scaler_X
        mlp_model.scaler_y = self.scaler_y
        mlp_model.framework = self.framework
        mlp_model.is_fitted = True
        
        return mlp_model.predict(X)