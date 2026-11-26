"""Simulador híbrido de defensa naval, implementado solo con la biblioteca estándar."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, replace
from enum import Enum
from statistics import mean
from typing import Any


GRAVITY_MPS2 = 9.81
MONTE_CARLO_THREAT_COUNTS = (5, 10, 20)
MONTE_CARLO_MIN_RUNS = 100
MONTE_CARLO_MAX_RUNS = 1000
WILSON_Z_95 = 1.959963984540054


class ThreatState(str, Enum):
    """Estados S0-S6 del autómata finito de cada amenaza."""

    UNDETECTED = "S0"
    TRACKED = "S1"
    EVALUATED = "S2"
    ENGAGED = "S3"
    NEUTRALIZED = "S4"
    IMPACT = "S5"
    HARMLESS = "S6"


class AttackProfile(str, Enum):
    BALLISTIC = "ballistic"
    SEA_SKIMMING = "sea_skimming"


TERMINAL_STATES = {
    ThreatState.NEUTRALIZED,
    ThreatState.IMPACT,
    ThreatState.HARMLESS,
}


@dataclass(frozen=True)
class SimulationConfig:
    """Parámetros validados; los valores predeterminados son un escenario ejecutable."""

    seed: int = 7
    mode: str = "est"
    duration_s: float = 90.0
    dt_s: float = 0.02
    air_density_kg_m3: float = 1.225
    wind_speed_mps: float = 8.0
    wind_sigma_mps: float = 0.8
    wind_direction_rad: float | None = None
    wave_height_m: float | None = None
    clutter_intensity: float = 2.0
    radar_height_m: float = 20.0
    radar_range_km: float = 40.0
    sweep_period_s: float = 1.0
    tracking_capacity: int = 16
    detection_probability: float = 0.9
    tti_threshold_s: float = 8.0
    fire_control_latency_s: float = 1.0
    interceptor_count: int = 16
    interceptor_speed_mps: float = 900.0
    fuze_radius_m: float = 10.0
    kill_probability: float = 0.8
    threat_count: int = 5
    salvo_interval_s: float = 2.0
    protection_radius_m: float = 1000.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SimulationConfig":
        if not isinstance(payload, dict):
            raise ValueError("El payload debe ser un objeto JSON.")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Parámetros desconocidos: {', '.join(sorted(unknown))}.")

        config = cls(**payload)
        if isinstance(config.seed, bool) or not isinstance(config.seed, int):
            raise ValueError("'seed' debe ser un entero.")
        if config.mode not in {"det", "est"}:
            raise ValueError("'mode' debe ser 'det' o 'est'.")
        _bounded("duration_s", config.duration_s, 0.0, 600.0, lower_open=True)
        _bounded("dt_s", config.dt_s, 0.001, 0.05)
        _bounded("air_density_kg_m3", config.air_density_kg_m3, 1.0, 1.225)
        _bounded("wind_speed_mps", config.wind_speed_mps, 0.0, 20.0)
        _bounded("wind_sigma_mps", config.wind_sigma_mps, 0.0, 5.0)
        _optional_bounded("wind_direction_rad", config.wind_direction_rad, 0.0, 2 * math.pi)
        if config.wind_direction_rad == 2 * math.pi:
            raise ValueError("'wind_direction_rad' debe ser menor que 2*pi.")
        _optional_bounded("wave_height_m", config.wave_height_m, 0.0, 4.0)
        _bounded("clutter_intensity", config.clutter_intensity, 0.0, 5.0)
        _bounded("radar_height_m", config.radar_height_m, 1.0, 100.0)
        _bounded("radar_range_km", config.radar_range_km, 20.0, 60.0)
        _bounded("sweep_period_s", config.sweep_period_s, 0.5, 4.0)
        _bounded("tracking_capacity", config.tracking_capacity, 8, 32, integer=True)
        _bounded("detection_probability", config.detection_probability, 0.0, 1.0)
        _bounded("tti_threshold_s", config.tti_threshold_s, 3.0, 15.0)
        _bounded("fire_control_latency_s", config.fire_control_latency_s, 0.5, 3.0)
        _bounded("interceptor_count", config.interceptor_count, 8, 40, integer=True)
        _bounded("interceptor_speed_mps", config.interceptor_speed_mps, 600.0, 1200.0)
        _bounded("fuze_radius_m", config.fuze_radius_m, 5.0, 20.0)
        _bounded("kill_probability", config.kill_probability, 0.6, 0.95)
        _bounded("threat_count", config.threat_count, 5, 20, integer=True)
        if config.threat_count not in {5, 10, 20}:
            raise ValueError("'threat_count' debe ser 5, 10 o 20.")
        _bounded("salvo_interval_s", config.salvo_interval_s, 0.5, 5.0)
        _bounded("protection_radius_m", config.protection_radius_m, 100.0, 10000.0)
        return config


def _bounded(
    name: str,
    value: Any,
    lower: float,
    upper: float,
    *,
    integer: bool = False,
    lower_open: bool = False,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' debe ser numérico.")
    if not math.isfinite(value):
        raise ValueError(f"'{name}' debe ser finito.")
    if integer and not isinstance(value, int):
        raise ValueError(f"'{name}' debe ser entero.")
    too_low = value <= lower if lower_open else value < lower
    if too_low or value > upper:
        opening = "(" if lower_open else "["
        raise ValueError(f"'{name}' debe estar en {opening}{lower}, {upper}].")


def _optional_bounded(name: str, value: Any, lower: float, upper: float) -> None:
    if value is not None:
        _bounded(name, value, lower, upper)


@dataclass
class Threat:
    """Amenaza con estado físico continuo y estado discreto del FSM."""

    identifier: int
    position: list[float]
    velocity: list[float]
    mass_kg: float
    drag_coefficient: float
    frontal_area_m2: float
    profile: AttackProfile
    target_x_m: float
    target_y_m: float
    state: ThreatState = ThreatState.UNDETECTED
    evaluated_at_s: float | None = None
    impact_x_m: float | None = None
    impact_y_m: float | None = None
    detection_attempts: int = 0


@dataclass
class Interceptor:
    """Interceptor guiado por navegación proporcional (PN)."""

    target_id: int
    position: list[float]
    velocity: list[float]
    speed_mps: float
    launch_at_s: float
    previous_distance_m: float
    deadline_s: float
    launched: bool = False


@dataclass
class Environment:
    wind_speed_mps: float
    wind_direction_rad: float
    wave_height_m: float
    current_time_s: float = 0.0
    wind_x_mps: float = 0.0
    wind_y_mps: float = 0.0

    def refresh_wind(self, rng: random.Random, config: SimulationConfig) -> None:
        # El paseo aleatorio acotado modela la variación estocástica del viento.
        if config.mode == "est":
            self.wind_speed_mps = min(
                20.0,
                max(0.0, self.wind_speed_mps + rng.gauss(0.0, config.wind_sigma_mps)),
            )
        self.wind_x_mps = self.wind_speed_mps * math.cos(self.wind_direction_rad)
        self.wind_y_mps = self.wind_speed_mps * math.sin(self.wind_direction_rad)

    def pitch_rad(self) -> float:
        # Movimiento de cabeceo sinusoidal acoplado a la amplitud del oleaje.
        amplitude = 0.1 * min(1.0, self.wave_height_m / 4.0)
        return amplitude * math.sin(0.7 * self.current_time_s)


class NavalDefenseSimulation:
    """Combina integración física por pasos fijos y eventos discretos de radar/fuego."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.rng = random.Random(config.seed)
        self.time_s = 0.0
        self.ship_position = [0.0, 0.0, 0.0]
        self.threats: list[Threat] = []
        self.interceptors: list[Interceptor] = []
        self.pending_fire: set[int] = set()
        self.initial_interceptors = config.interceptor_count
        self.remaining_interceptors = config.interceptor_count
        self.next_launch_s = 0.0
        self.next_sweep_s = 0.0
        self.next_environment_update_s = 0.0
        self.fire_control_available_s = 0.0
        self.detections = 0
        self.failed_detections = 0
        self.neutralized_count = 0
        self.impact_count = 0
        self.harmless_count = 0
        self.intercept_attempts = 0
        self.interceptor_misses = 0
        self.failed_detonations = 0
        self.max_queue_length = 0
        self.wait_times: list[float] = []

        if config.mode == "det":
            wind_speed = 0.0
            wind_direction = 0.0
            wave_height = 0.0
        else:
            wind_speed = config.wind_speed_mps
            wind_direction = (
                config.wind_direction_rad
                if config.wind_direction_rad is not None
                else self.rng.uniform(0.0, 2 * math.pi)
            )
            wave_height = (
                config.wave_height_m
                if config.wave_height_m is not None
                else self.rng.uniform(0.0, 4.0)
            )
        self.environment = Environment(wind_speed, wind_direction, wave_height)
        self.environment.refresh_wind(self.rng, config)

    def _uniform(self, low: float, high: float) -> float:
        if self.config.mode == "det":
            return (low + high) / 2.0
        return self.rng.uniform(low, high)

    def _chance(self, probability: float) -> bool:
        # En modo determinista se usa el valor esperado; en estocástico, Bernoulli con semilla fija.
        if self.config.mode == "det":
            return probability >= 0.5
        return self.rng.random() < probability

    def _poisson(self, rate: float) -> int:
        # Muestreo de Poisson (Knuth), para ecos de clutter por barrido.
        if self.config.mode == "det" or rate <= 0.0:
            return 0
        threshold = math.exp(-rate)
        product = 1.0
        count = 0
        while product > threshold:
            count += 1
            product *= self.rng.random()
        return count - 1

    def _new_threat(self, identifier: int) -> Threat:
        config = self.config
        if config.mode == "det":
            profile = (
                AttackProfile.BALLISTIC
                if identifier % 2 == 0
                else AttackProfile.SEA_SKIMMING
            )
            is_lethal = identifier % 3 != 0
        else:
            profile = (
                AttackProfile.BALLISTIC
                if self._uniform(0.0, 1.0) < 0.5
                else AttackProfile.SEA_SKIMMING
            )
            is_lethal = self._uniform(0.0, 1.0) < 0.7
        angle = self._uniform(0.0, 2 * math.pi)
        target_radius = (
            self._uniform(0.0, config.protection_radius_m * 0.8)
            if is_lethal
            else self._uniform(config.protection_radius_m + 1000.0, config.protection_radius_m + 8000.0)
        )
        target_x = self.ship_position[0] + target_radius * math.cos(angle)
        target_y = self.ship_position[1] + target_radius * math.sin(angle)

        speed = self._uniform(200.0, 1000.0)
        if profile == AttackProfile.BALLISTIC:
            altitude = self._uniform(2000.0, 8000.0)
            vertical_speed = 0.0
            distance = 0.0
        else:
            altitude = self._uniform(60.0, 120.0)
            # La amenaza mantiene altura durante la aproximación y desciende en la fase terminal.
            distance = max(6000.0, min(20000.0, speed * self._uniform(10.0, 20.0)))
            vertical_speed = 0.0

        outward_x, outward_y = math.cos(angle), math.sin(angle)
        mass = self._uniform(100.0, 700.0)
        drag_coefficient = self._uniform(0.2, 0.6)
        frontal_area = self._uniform(0.05, 0.3)
        position = [
            target_x + outward_x * distance,
            target_y + outward_y * distance,
            altitude,
        ]
        velocity = [-outward_x * speed, -outward_y * speed, vertical_speed]
        threat = Threat(
            identifier=identifier,
            position=position,
            velocity=velocity,
            mass_kg=mass,
            drag_coefficient=drag_coefficient,
            frontal_area_m2=frontal_area,
            profile=profile,
            target_x_m=target_x,
            target_y_m=target_y,
        )
        if profile == AttackProfile.BALLISTIC:
            # Sitúa el lanzamiento donde la trayectoria con arrastre alcance el punto previsto.
            threat.position = [0.0, 0.0, altitude]
            displacement_x, displacement_y = self._project_impact(threat)
            threat.position = [
                target_x - displacement_x,
                target_y - displacement_y,
                altitude,
            ]
        return threat

    def _spawn_due_threats(self) -> None:
        while (
            len(self.threats) < self.config.threat_count
            and self.time_s + 1e-12 >= self.next_launch_s
        ):
            self.threats.append(self._new_threat(len(self.threats) + 1))
            self.next_launch_s += self.config.salvo_interval_s

    def _active_track_count(self) -> int:
        return sum(
            threat.state in {
                ThreatState.TRACKED,
                ThreatState.EVALUATED,
                ThreatState.ENGAGED,
            }
            for threat in self.threats
        )

    def _radar_limit_m(self, threat: Threat) -> float:
        # Horizonte radar: 3.57*(sqrt(h_antena)+sqrt(h_objetivo)) kilómetros.
        antenna_height = max(
            0.1,
            self.config.radar_height_m + 2.0 * math.sin(self.environment.pitch_rad()),
        )
        target_height = max(0.0, threat.position[2])
        horizon_km = 3.57 * (math.sqrt(antenna_height) + math.sqrt(target_height))
        return min(self.config.radar_range_km, horizon_km) * 1000.0

    def _radar_sweep(self) -> None:
        clutter = self._poisson(self.config.clutter_intensity)
        capacity_available = self.config.tracking_capacity - self._active_track_count()
        for threat in self.threats:
            if threat.state == ThreatState.TRACKED:
                # S1->S0 representa pérdida de seguimiento en un nuevo barrido.
                if self._within_radar(threat) and self._detection_chance(threat, clutter):
                    self._evaluate(threat)
                    if threat.state in TERMINAL_STATES:
                        capacity_available += 1
                else:
                    threat.state = ThreatState.UNDETECTED
                    capacity_available += 1
                continue
            if threat.state != ThreatState.UNDETECTED:
                continue
            if capacity_available <= 0 or not self._within_radar(threat):
                self.failed_detections += 1
                continue
            threat.detection_attempts += 1
            if self._detection_chance(threat, clutter):
                threat.state = ThreatState.TRACKED
                self.detections += 1
                capacity_available -= 1
            else:
                self.failed_detections += 1

    def _within_radar(self, threat: Threat) -> bool:
        dx = threat.position[0] - self.ship_position[0]
        dy = threat.position[1] - self.ship_position[1]
        dz = threat.position[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        return distance <= self._radar_limit_m(threat)

    def _detection_chance(self, threat: Threat, clutter: int) -> bool:
        dx = threat.position[0] - self.ship_position[0]
        dy = threat.position[1] - self.ship_position[1]
        distance_km = math.hypot(dx, dy) / 1000.0
        range_factor = max(0.1, 1.0 - 0.35 * distance_km / self.config.radar_range_km)
        clutter_factor = math.exp(-0.15 * clutter)
        probability = min(
            1.0,
            self.config.detection_probability * range_factor * clutter_factor,
        )
        return self._chance(probability)

    def _project_impact(self, threat: Threat) -> tuple[float, float]:
        # Predicción más gruesa que dt: se refina cerca del impacto sin cambiar la física integrada.
        position = threat.position.copy()
        velocity = threat.velocity.copy()
        elapsed = 0.0
        while elapsed < 300.0:
            forecast_step = (
                0.25
                if position[2] > 250.0
                or (
                    threat.profile == AttackProfile.SEA_SKIMMING
                    and position[2] > 20.0
                )
                else 0.05
            )
            forecast_step = min(forecast_step, 300.0 - elapsed)
            acceleration = self._acceleration(threat, position, velocity)
            for axis in range(3):
                velocity[axis] += acceleration[axis] * forecast_step
                position[axis] += velocity[axis] * forecast_step
            if position[2] <= 0.0:
                return position[0], position[1]
            elapsed += forecast_step
        return position[0], position[1]

    def _evaluate(self, threat: Threat) -> None:
        threat.impact_x_m, threat.impact_y_m = self._project_impact(threat)
        distance_to_ship = math.hypot(
            threat.impact_x_m - self.ship_position[0],
            threat.impact_y_m - self.ship_position[1],
        )
        threat.state = ThreatState.EVALUATED
        threat.evaluated_at_s = self.time_s
        if distance_to_ship > self.config.protection_radius_m:
            threat.state = ThreatState.HARMLESS
            self.harmless_count += 1
        else:
            self.pending_fire.add(threat.identifier)

    def _tti_s(self, threat: Threat) -> float:
        dx = threat.position[0] - self.ship_position[0]
        dy = threat.position[1] - self.ship_position[1]
        distance = math.hypot(dx, dy)
        if distance <= 0.0:
            return 0.0
        closing_speed = -(
            dx * threat.velocity[0] + dy * threat.velocity[1]
        ) / distance
        return distance / max(1.0, closing_speed)

    def _dispatch_fire_control(self) -> None:
        if (
            self.time_s + 1e-12 < self.fire_control_available_s
            or self.remaining_interceptors <= 0
        ):
            return
        candidates = [
            threat
            for threat in self.threats
            if threat.identifier in self.pending_fire
            and threat.state == ThreatState.EVALUATED
        ]
        # La cola prioriza amenazas bajo el umbral TTI y, dentro de cada grupo, las más urgentes.
        candidates.sort(
            key=lambda threat: (
                self._tti_s(threat) > self.config.tti_threshold_s,
                self._tti_s(threat),
                threat.identifier,
            )
        )
        for threat in candidates:
            distance = math.dist(self.ship_position, threat.position)
            flight_time = distance / self.config.interceptor_speed_mps
            tti = self._tti_s(threat)
            if tti < self.config.fire_control_latency_s + flight_time:
                continue
            launch_position = self.ship_position.copy()
            interceptor = Interceptor(
                target_id=threat.identifier,
                position=launch_position,
                velocity=[0.0, 0.0, 0.0],
                speed_mps=self.config.interceptor_speed_mps,
                launch_at_s=self.time_s + self.config.fire_control_latency_s,
                previous_distance_m=distance,
                deadline_s=self.time_s
                + self.config.fire_control_latency_s
                + max(10.0, min(90.0, 2.0 * flight_time)),
            )
            self.interceptors.append(interceptor)
            self.pending_fire.remove(threat.identifier)
            threat.state = ThreatState.ENGAGED
            self.remaining_interceptors -= 1
            self.intercept_attempts += 1
            if threat.evaluated_at_s is not None:
                self.wait_times.append(max(0.0, self.time_s - threat.evaluated_at_s))
            self.fire_control_available_s = (
                self.time_s + self.config.fire_control_latency_s
            )
            return

    def _acceleration(
        self,
        threat: Threat,
        position: list[float],
        velocity: list[float],
    ) -> list[float]:
        # Arrastre cuadrático respecto al viento, gravedad y control de vuelo rasante.
        relative_x = velocity[0] - self.environment.wind_x_mps
        relative_y = velocity[1] - self.environment.wind_y_mps
        relative_z = velocity[2]
        relative_speed = math.sqrt(
            relative_x * relative_x
            + relative_y * relative_y
            + relative_z * relative_z
        )
        drag_scale = (
            -0.5
            * self.config.air_density_kg_m3
            * threat.drag_coefficient
            * threat.frontal_area_m2
            * relative_speed
            / threat.mass_kg
        )
        acceleration_x = drag_scale * relative_x
        acceleration_y = drag_scale * relative_y
        acceleration_z = drag_scale * relative_z
        if threat.profile == AttackProfile.SEA_SKIMMING:
            remaining = math.hypot(
                threat.target_x_m - position[0],
                threat.target_y_m - position[1],
            )
            horizontal_speed = math.hypot(velocity[0], velocity[1])
            fall_time = (
                velocity[2]
                + math.sqrt(
                    velocity[2] ** 2 + 2.0 * GRAVITY_MPS2 * max(0.0, position[2])
                )
            ) / GRAVITY_MPS2
            terminal_range = horizontal_speed * max(0.0, fall_time)
            if remaining > terminal_range and horizontal_speed > 50.0:
                # Control vertical sencillo que conserva la altura de vuelo rasante.
                acceleration_z += (
                    GRAVITY_MPS2 - 0.8 * (position[2] - 80.0) - 1.5 * velocity[2]
                )
            else:
                acceleration_z -= GRAVITY_MPS2
        else:
            acceleration_z -= GRAVITY_MPS2
        return [acceleration_x, acceleration_y, acceleration_z]

    def _integrate_threat(self, threat: Threat, dt: float) -> None:
        # Integración explícita de Euler: x(k+1)=f(x(k),u(k),w(k)).
        acceleration = self._acceleration(threat, threat.position, threat.velocity)
        for axis in range(3):
            threat.velocity[axis] += acceleration[axis] * dt
            threat.position[axis] += threat.velocity[axis] * dt

    def _impact_state(self, threat: Threat) -> None:
        distance = math.hypot(
            threat.position[0] - self.ship_position[0],
            threat.position[1] - self.ship_position[1],
        )
        if distance <= self.config.protection_radius_m:
            threat.state = ThreatState.IMPACT
            self.impact_count += 1
        else:
            threat.state = ThreatState.HARMLESS
            self.harmless_count += 1
        self.pending_fire.discard(threat.identifier)

    def _move_ship(self, dt: float) -> None:
        # Deriva simplificada del buque: fracción pequeña de la velocidad del viento.
        self.ship_position[0] += self.environment.wind_x_mps * 0.01 * dt
        self.ship_position[1] += self.environment.wind_y_mps * 0.01 * dt

    def _guide_interceptors(self, dt: float) -> None:
        threats_by_id = {threat.identifier: threat for threat in self.threats}
        survivors: list[Interceptor] = []
        for interceptor in self.interceptors:
            target = threats_by_id[interceptor.target_id]
            if target.state in TERMINAL_STATES:
                continue
            if self.time_s + 1e-12 < interceptor.launch_at_s:
                survivors.append(interceptor)
                continue
            if not interceptor.launched:
                line = [
                    target.position[axis] - interceptor.position[axis]
                    for axis in range(3)
                ]
                distance = math.sqrt(sum(component * component for component in line))
                if distance <= 1e-9:
                    self._resolve_detonation(target)
                    continue
                interceptor.velocity = [
                    component * interceptor.speed_mps / distance for component in line
                ]
                interceptor.launched = True

            relative_position = [
                target.position[axis] - interceptor.position[axis] for axis in range(3)
            ]
            distance = math.sqrt(sum(component * component for component in relative_position))
            if distance <= self.config.fuze_radius_m:
                self._resolve_detonation(target)
                continue

            relative_velocity = [
                target.velocity[axis] - interceptor.velocity[axis] for axis in range(3)
            ]
            los_rate = _cross(relative_position, relative_velocity)
            range_squared = max(1e-9, distance * distance)
            los_rate = [component / range_squared for component in los_rate]
            closing_speed = -sum(
                relative_position[axis] * relative_velocity[axis] for axis in range(3)
            ) / distance
            los_unit = [component / distance for component in relative_position]
            # Navegación proporcional: a = N * V_c * (dLOS x LOS).
            acceleration = [
                3.0 * max(0.0, closing_speed) * component
                for component in _cross(los_rate, los_unit)
            ]
            velocity = [
                interceptor.velocity[axis] + acceleration[axis] * dt
                for axis in range(3)
            ]
            velocity_norm = math.sqrt(sum(component * component for component in velocity))
            if velocity_norm > 0.0:
                interceptor.velocity = [
                    component * interceptor.speed_mps / velocity_norm
                    for component in velocity
                ]
            for axis in range(3):
                interceptor.position[axis] += interceptor.velocity[axis] * dt

            new_distance = math.dist(interceptor.position, target.position)
            if new_distance <= self.config.fuze_radius_m:
                self._resolve_detonation(target)
                continue
            if (
                self.time_s >= interceptor.deadline_s
                or (
                    new_distance > interceptor.previous_distance_m
                    and interceptor.previous_distance_m < 1000.0
                )
            ):
                self.interceptor_misses += 1
                target.state = ThreatState.EVALUATED
                target.evaluated_at_s = self.time_s
                self.pending_fire.add(target.identifier)
                continue
            interceptor.previous_distance_m = new_distance
            survivors.append(interceptor)
        self.interceptors = survivors

    def _resolve_detonation(self, target: Threat) -> None:
        # Pk se muestrea con la semilla fija incluso en modo det, para admitir fallos reproducibles.
        if self.rng.random() < self.config.kill_probability:
            target.state = ThreatState.NEUTRALIZED
            self.neutralized_count += 1
            self.pending_fire.discard(target.identifier)
        else:
            # Fallo de espoleta/intercepción: S3->S2 permite reevaluación y reenganche.
            self.failed_detonations += 1
            target.state = ThreatState.EVALUATED
            target.evaluated_at_s = self.time_s
            self.pending_fire.add(target.identifier)

    def _finished(self) -> bool:
        return (
            len(self.threats) == self.config.threat_count
            and all(threat.state in TERMINAL_STATES for threat in self.threats)
        )

    def run(self) -> dict[str, Any]:
        steps = math.ceil(self.config.duration_s / self.config.dt_s)
        for step in range(steps + 1):
            self.time_s = min(step * self.config.dt_s, self.config.duration_s)
            step_dt = min(self.config.dt_s, self.config.duration_s - self.time_s)
            self.environment.current_time_s = self.time_s
            self._spawn_due_threats()

            if self.time_s + 1e-12 >= self.next_environment_update_s:
                self.environment.refresh_wind(self.rng, self.config)
                self.next_environment_update_s += 1.0
            if self.time_s + 1e-12 >= self.next_sweep_s:
                self._radar_sweep()
                self.next_sweep_s += self.config.sweep_period_s

            # S1 pasa a evaluación en el siguiente barrido; S2 espera turno en la cola de fuego.
            self._dispatch_fire_control()
            active_threats = [
                threat for threat in self.threats if threat.state not in TERMINAL_STATES
            ]
            for threat in active_threats:
                self._integrate_threat(threat, step_dt)
                if threat.position[2] <= 0.0:
                    self._impact_state(threat)
            self._move_ship(step_dt)
            self._guide_interceptors(step_dt)
            self.max_queue_length = max(self.max_queue_length, len(self.pending_fire))

            if self._finished():
                break

        return self._result()

    def _result(self) -> dict[str, Any]:
        processed = self.neutralized_count + self.impact_count + self.harmless_count
        terminal_counts = {
            state.value: sum(threat.state == state for threat in self.threats)
            for state in ThreatState
        }
        threat_results = []
        for threat in self.threats:
            threat_results.append(
                {
                    "id": threat.identifier,
                    "state": threat.state.value,
                    "profile": threat.profile.value,
                    "position_m": [_rounded(value) for value in threat.position],
                    "impact_point_m": (
                        [_rounded(threat.impact_x_m), _rounded(threat.impact_y_m)]
                        if threat.impact_x_m is not None and threat.impact_y_m is not None
                        else None
                    ),
                    "detection_attempts": threat.detection_attempts,
                }
            )
        return {
            "seed": self.config.seed,
            "mode": self.config.mode,
            "simulation_time_s": _rounded(self.time_s),
            "throughput_per_s": _rounded(processed / self.time_s) if self.time_s > 0 else 0.0,
            "average_wait_time_s": _rounded(mean(self.wait_times)) if self.wait_times else 0.0,
            "counts": {
                "spawned": len(self.threats),
                "processed": processed,
                "detected": self.detections,
                "failed_detection_attempts": self.failed_detections,
                "neutralized": self.neutralized_count,
                "impacts": self.impact_count,
                "harmless": self.harmless_count,
                "intercept_attempts": self.intercept_attempts,
                "interceptor_misses": self.interceptor_misses,
                "failed_detonations": self.failed_detonations,
                "interceptors_remaining": self.remaining_interceptors,
                "pending_fire_queue": len(self.pending_fire),
                "max_fire_queue": self.max_queue_length,
                "states": terminal_counts,
            },
            "environment": {
                "air_density_kg_m3": _rounded(self.config.air_density_kg_m3),
                "wind_speed_mps": _rounded(self.environment.wind_speed_mps),
                "wind_direction_rad": _rounded(self.environment.wind_direction_rad),
                "wave_height_m": _rounded(self.environment.wave_height_m),
                "ship_pitch_rad": _rounded(self.environment.pitch_rad()),
            },
            "threats": threat_results,
        }


def _cross(left: list[float], right: list[float]) -> list[float]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _rounded(value: float) -> float:
    return round(value, 6)


def run_simulation(payload: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta una simulación desde un diccionario y devuelve datos serializables a JSON."""

    return NavalDefenseSimulation(SimulationConfig.from_payload(payload)).run()


def prepare_monte_carlo(payload: dict[str, Any]) -> tuple[SimulationConfig, int]:
    """Valida una solicitud Monte Carlo y devuelve sus parámetros base."""

    if not isinstance(payload, dict):
        raise ValueError("El payload Monte Carlo debe ser un objeto JSON.")
    runs = payload.get("runs", MONTE_CARLO_MIN_RUNS)
    if isinstance(runs, bool) or not isinstance(runs, int):
        raise ValueError("'runs' debe ser un entero.")
    if not MONTE_CARLO_MIN_RUNS <= runs <= MONTE_CARLO_MAX_RUNS:
        raise ValueError(
            f"'runs' debe estar entre {MONTE_CARLO_MIN_RUNS} y {MONTE_CARLO_MAX_RUNS}."
        )
    base_payload = {key: value for key, value in payload.items() if key != "runs"}
    config = SimulationConfig.from_payload(base_payload)
    if config.mode != "est":
        raise ValueError("Monte Carlo requiere el modo estocástico ('mode': 'est').")
    minimum_duration = (
        max(MONTE_CARLO_THREAT_COUNTS) - 1
    ) * config.salvo_interval_s
    if config.duration_s < minimum_duration:
        raise ValueError(
            "'duration_s' debe permitir lanzar las 20 amenazas; "
            f"mínimo: {minimum_duration:g} s."
        )
    return config, runs


def wilson_confidence_interval(successes: int, trials: int) -> tuple[float, float]:
    """Intervalo de confianza binomial Wilson bilateral al 95 %."""

    if isinstance(successes, bool) or not isinstance(successes, int):
        raise ValueError("'successes' debe ser un entero.")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise ValueError("'trials' debe ser un entero positivo.")
    if not 0 <= successes <= trials:
        raise ValueError("'successes' debe estar entre cero y 'trials'.")

    proportion = successes / trials
    z_squared = WILSON_Z_95**2
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    margin = (
        WILSON_Z_95
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z_squared / (4.0 * trials**2)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def run_monte_carlo(payload: dict[str, Any]) -> dict[str, Any]:
    """Estima supervivencia del buque para salvas de 5, 10 y 20 amenazas."""

    base_config, runs = prepare_monte_carlo(payload)
    groups = []
    for threat_count in MONTE_CARLO_THREAT_COUNTS:
        surviving_runs = 0
        runs_with_impacts = 0
        total_impacts = 0
        for replication in range(runs):
            # La misma semilla de réplica en cada grupo permite comparar tamaños de salva.
            config = replace(
                base_config,
                seed=base_config.seed + replication,
                threat_count=threat_count,
            )
            result = NavalDefenseSimulation(config).run()
            impacts = result["counts"]["impacts"]
            total_impacts += impacts
            if impacts == 0:
                surviving_runs += 1
            else:
                runs_with_impacts += 1

        lower, upper = wilson_confidence_interval(surviving_runs, runs)
        survival_rate = surviving_runs / runs
        groups.append(
            {
                "threat_count": threat_count,
                "runs": runs,
                "surviving_runs": surviving_runs,
                "runs_with_impacts": runs_with_impacts,
                "total_impacts": total_impacts,
                "survival_rate": _rounded(survival_rate),
                "survival_rate_percent": _rounded(survival_rate * 100.0),
                "confidence_interval_95": {
                    "lower": _rounded(lower),
                    "upper": _rounded(upper),
                },
                "confidence_interval_95_percent": {
                    "lower": _rounded(lower * 100.0),
                    "upper": _rounded(upper * 100.0),
                },
            }
        )

    return {
        "metric": "supervivencia del buque: corridas sin impactos durante el horizonte simulado",
        "confidence_level": 0.95,
        "interval_method": "Wilson",
        "mode": base_config.mode,
        "base_seed": base_config.seed,
        "duration_s": base_config.duration_s,
        "salvo_interval_s": base_config.salvo_interval_s,
        "runs_per_group": runs,
        "total_runs": runs * len(MONTE_CARLO_THREAT_COUNTS),
        "seed_scheme": "seed = base_seed + índice_de_réplica; semillas emparejadas entre grupos",
        "groups": groups,
    }


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Entrypoint compatible con AWS Lambda; también acepta el payload directamente."""

    del context
    payload = event.get("body", event) if isinstance(event, dict) else event
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("El campo 'body' debe contener JSON válido.") from error
    if not isinstance(payload, dict):
        raise ValueError("El evento debe contener un objeto JSON.")
    operation = payload.get("operation")
    if operation == "monte_carlo":
        return run_monte_carlo(
            {key: value for key, value in payload.items() if key != "operation"}
        )
    if operation is not None:
        raise ValueError("'operation' debe ser 'monte_carlo' cuando se especifica.")
    return run_simulation(payload)


if __name__ == "__main__":
    print(json.dumps(run_simulation({}), indent=2, ensure_ascii=False))
