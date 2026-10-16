"""Unit tests for individual language parsers."""

from __future__ import annotations

import pytest
from graphagent.language_registry import default_registry
from graphagent.models import NodeType


def test_python_parser():
    parser = default_registry.get_parser_for_language("python")
    assert parser is not None

    code = b"""
import os
from math import sqrt

class Animal:
    def speak(self) -> str:
        return "..."

class Dog(Animal):
    def speak(self) -> str:
        return "woof"

def create_dog():
    d = Dog()
    return d.speak()
"""
    result = parser.parse("animals.py", code, "animals.py")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "Animal" in names
    assert names["Animal"].type == NodeType.CLASS.value

    assert "Dog" in names
    assert names["Dog"].type == NodeType.CLASS.value

    assert "speak" in names
    assert names["speak"].type == NodeType.METHOD.value

    assert "create_dog" in names
    assert names["create_dog"].type == NodeType.FUNCTION.value

    # Inheritance
    assert len(result.raw_inheritances) == 1
    assert result.raw_inheritances[0].base_name == "Animal"

    # Calls
    called_names = [c.called_name for c in result.raw_calls]
    assert "Dog" in called_names or "speak" in called_names


def test_typescript_parser():
    parser = default_registry.get_parser_for_language("typescript")
    assert parser is not None

    code = b"""
import { logger } from './logger';

export interface Greeter {
    greet(name: string): string;
}

export class HelloService implements Greeter {
    greet(name: string): string {
        logger(name);
        return "Hello " + name;
    }
}
"""
    result = parser.parse("service.ts", code, "service.ts")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "Greeter" in names
    assert names["Greeter"].type == NodeType.INTERFACE.value
    assert "HelloService" in names
    assert names["HelloService"].type == NodeType.CLASS.value
    assert "greet" in names

    assert len(result.raw_inheritances) >= 1
    assert result.raw_inheritances[0].base_name == "Greeter"
    assert result.raw_inheritances[0].is_interface is True


def test_java_parser():
    parser = default_registry.get_parser_for_language("java")
    assert parser is not None

    code = b"""
package com.demo;
import java.util.List;

public class MathService extends BaseService implements IService {
    public int multiply(int a, int b) {
        log(a, b);
        return a * b;
    }
}
"""
    result = parser.parse("MathService.java", code, "MathService.java")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "MathService" in names
    assert names["MathService"].type == NodeType.CLASS.value
    assert "multiply" in names
    assert names["multiply"].type == NodeType.METHOD.value

    base_names = [inh.base_name for inh in result.raw_inheritances]
    assert "BaseService" in base_names
    assert "IService" in base_names


def test_go_parser():
    parser = default_registry.get_parser_for_language("go")
    assert parser is not None

    code = b"""
package main
import "fmt"

type Worker struct {
    ID int
}

func (w *Worker) Work() {
    fmt.Println(w.ID)
}

func Run() {
    w := &Worker{ID: 1}
    w.Work()
}
"""
    result = parser.parse("main.go", code, "main.go")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "Worker" in names
    assert names["Worker"].type == NodeType.STRUCT.value
    assert "Work" in names
    assert names["Work"].type == NodeType.METHOD.value
    assert "Run" in names
    assert names["Run"].type == NodeType.FUNCTION.value


def test_rust_parser():
    parser = default_registry.get_parser_for_language("rust")
    assert parser is not None

    code = b"""
pub trait Flyable {
    fn fly(&self);
}

pub struct Drone {
    pub altitude: u32,
}

impl Flyable for Drone {
    fn fly(&self) {
        println!("Flying");
    }
}
"""
    result = parser.parse("lib.rs", code, "lib.rs")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "Flyable" in names
    assert names["Flyable"].type == NodeType.TRAIT.value
    assert "Drone" in names
    assert names["Drone"].type == NodeType.STRUCT.value
    assert "fly" in names
    assert names["fly"].type == NodeType.METHOD.value


def test_c_cpp_parser():
    parser = default_registry.get_parser_for_language("cpp")
    assert parser is not None

    code = b"""
#include <iostream>

class Engine {
public:
    void start() {}
};

int main() {
    Engine e;
    e.start();
    return 0;
}
"""
    result = parser.parse("main.cpp", code, "main.cpp")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "Engine" in names
    assert names["Engine"].type == NodeType.CLASS.value
    assert "main" in names
    assert names["main"].type == NodeType.FUNCTION.value


def test_php_parser():
    parser = default_registry.get_parser_for_language("php")
    assert parser is not None

    code = b"""<?php
namespace App;

interface CacheInterface {}

class RedisCache implements CacheInterface {
    public function get($key) {
        return null;
    }
}
"""
    result = parser.parse("cache.php", code, "cache.php")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "CacheInterface" in names
    assert names["CacheInterface"].type == NodeType.INTERFACE.value
    assert "RedisCache" in names
    assert names["RedisCache"].type == NodeType.CLASS.value
    assert "get" in names


def test_python_nested_functions():
    parser = default_registry.get_parser_for_language("python")
    assert parser is not None

    code = b"""
def outer_func(x):
    def inner_func(y):
        return y * 2
    return inner_func(x)
"""
    result = parser.parse("nested.py", code, "nested.py")
    assert result.success is True

    names = {n.name: n for n in result.nodes}
    assert "outer_func" in names
    assert "inner_func" in names
    assert names["outer_func"].type == NodeType.FUNCTION.value
    assert names["inner_func"].type == NodeType.FUNCTION.value
    # Verify inner function has outer function as parent
    assert names["inner_func"].parent_id == names["outer_func"].id


def test_syntax_error_resilience():
    parser = default_registry.get_parser_for_language("python")
    assert parser is not None

    # Code with intentional syntax errors (incomplete expression, missing operands)
    broken_code = b"""
def valid_func(a, b):
    return a + b

def broken_func():
    x = 1 +

def another_valid():
    return 42
"""
    result = parser.parse("broken.py", broken_code, "broken.py")
    assert result.success is True
    # Tree-sitter error recovery extracts valid symbols despite local syntax errors
    names = {n.name for n in result.nodes}
    assert "valid_func" in names
    assert "broken_func" in names
    assert "another_valid" in names


def test_duplicate_symbol_names():
    parser = default_registry.get_parser_for_language("python")
    code1 = b"def calculate(): return 1\n"
    code2 = b"def calculate(): return 2\n"

    res1 = parser.parse("service_a.py", code1, "service_a.py")
    res2 = parser.parse("service_b.py", code2, "service_b.py")

    node1 = next(n for n in res1.nodes if n.name == "calculate")
    node2 = next(n for n in res2.nodes if n.name == "calculate")

    assert node1.id != node2.id
    assert node1.id == "symbol:service_a.py:calculate"
    assert node2.id == "symbol:service_b.py:calculate"
