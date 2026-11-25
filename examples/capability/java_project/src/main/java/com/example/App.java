package com.example;

public final class App {
    private App() {
    }

    public static int add(int left, int right) {
        return left + right;
    }

    public static void main(String[] args) {
        System.out.println(add(1, 2));
    }
}
