package com.example;

public interface Service {
    void execute();
}

public class OrderService implements Service {
    public void execute() {
        System.out.println("Executing order service");
    }
}
